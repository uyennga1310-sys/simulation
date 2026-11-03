# -*- coding: utf-8 -*-
# ANSYS Electronics Desktop 2021 R1 - Maxwell 3D Eddy Current / Transient
# Printed ECT sensor starter automation
#
# Run from: AEDT -> Tools -> Run Script...
# Interpreter: IronPython bundled with AEDT.
#
# IMPORTANT:
# 1) Select your Parasolid .x_t file when the dialog opens.
# 2) After import, check the object names printed in the Message Manager.
# 3) Materials/terminal names are detected automatically when unambiguous.
#    Ambiguous objects use selection dialogs; no source-code editing required.
# 4) Settings below are examples, not calibrated sensor parameters.
#    This is an eddy-current TX/RX sensor model, not capacitive ECT.
# 5) Use solid copper traces with actual PCB copper thickness; represent
#    every spiral turn in the geometry (one conductor per terminal).
# 6) Run with IronPython inside AEDT 2021 R1, not CPython/PyAEDT.

import os
import re
import math
import datetime
import System
import clr

clr.AddReference("System.Windows.Forms")
from System.Windows.Forms import (OpenFileDialog, DialogResult, Form, Label,
                                  ComboBox, ComboBoxStyle, Button)

# ------------------------- USER SETTINGS -------------------------

PROJECT_NAME = "Printed_ECT_Maxwell"
SCRIPT_VERSION = "PCB-FREQ-2021R1-1"
SOLUTION_TYPE = "EddyCurrent"  # Frequency-domain; alternative: "Transient".
DESIGN_NAME = "ECT_PCB_Frequency"
# Proposed range, NOT specified by the slides. Each point adapts its own mesh.
SWEEP_START_HZ = 1e4
SWEEP_STOP_HZ = 1e6
SWEEP_POINTS = 9
# Current amplitude convention follows AEDT's selected solver, no implicit RMS conversion.
ADAPTIVE_PERCENT_ERROR = 1.0
MAX_ADAPTIVE_PASSES = 10
COPPER_THICKNESS_MM = 0.035  # EXAMPLE ONLY; replace with actual PCB stackup.
MESH_DIVISIONS_PER_SKIN_DEPTH = 2.0

MODEL_UNITS = "mm"

# Example excitation settings; replace with measured operating conditions.
FREQ_HZ = 100000.0
CURRENT_PEAK_A = 0.1
TRANSIENT_CYCLES = 10
TRANSIENT_STEPS_PER_CYCLE = 100
AUTO_SOLVE = False       # Inspect geometry, terminals and mesh before enabling.
OUTPUT_DIRECTORY = ""   # Empty: save beside imported geometry; never overwrite.
RX_TERMINAL_SHEETS = []  # Optional open-circuit pickup coil cross-section sheets.
# One sheet per independent conductor; do not select both ends of one coil.
TX_POINT_OUT = False
RX_POINT_OUT = False

# Approximate starting properties for C45. Replace with measured/material
# certificate data if available; steel permeability is nonlinear/frequency
# dependent, so this constant-mu model is only a first-pass approximation.
C45_RELATIVE_MU = "100"
C45_CONDUCTIVITY = "4e6"

# Put exact imported object names here after inspecting the imported model.
# Example:
# MATERIAL_OBJECTS = {
#     "copper": ["TX_Copper", "RX_Copper"],
#     "FR4_epoxy": ["PCB_Substrate"],
#     "C45": ["Specimen"]
# }
MATERIAL_OBJECTS = {
    "copper": [],
    "FR4_epoxy": [],
    "C45": [],
    "aluminum": []
}

# Coil terminal must be a SHEET created by cutting the TX copper conductor
# across its cross-section. Add the exact sheet name(s) here.
# Example: TX_TERMINAL_SHEETS = ["TX_CutSection"]
TX_TERMINAL_SHEETS = []

# Initial mesh limits only. Resolve actual copper thickness and specimen skin
# depth with a convergence study; 0.50 mm in steel may be too coarse at 100 kHz.
COPPER_MAX_LENGTH = "0.03mm"  # PPT baseline; tightened for skin depth/thickness.
STEEL_MAX_LENGTH = "0.03mm"  # Tightened at highest analyzed frequency.

# Region padding around imported sensor/specimen geometry.
REGION_PADDING_PERCENT = 100
# Check boundary-distance and mesh convergence before using numerical results.

# ------------------------- HELPERS -------------------------

def log(message):
    text = "[ECT " + SCRIPT_VERSION + "] " + str(message)
    print(text)
    desktop = globals().get("oDesktop")
    if desktop is not None:
        try:
            desktop.AddMessage("", "", 0, text)
        except Exception:
            pass  # Logging must not hide the original setup/solver error.

def assign_material(editor, object_names, material_name):
    if not object_names:
        log("SKIP material " + material_name + ": no object names configured.")
        return
    for obj in object_names:
        editor.AssignMaterial(
            ["NAME:Selections", "Selections:=", obj],
            ["NAME:Attributes",
             "MaterialValue:=", '"' + material_name + '"',
             "SolveInside:=", True]
        )
        log("Assigned " + material_name + " -> " + obj)

def choose_role(object_name, roles, description):
    dialog = Form()
    dialog.Text = "ECT - " + object_name
    dialog.Width = 640
    dialog.Height = 230
    label = Label()
    label.Text = description + "\nObject: " + object_name
    label.Left, label.Top, label.Width, label.Height = 15, 15, 590, 85
    choice = ComboBox()
    choice.Left, choice.Top, choice.Width = 15, 105, 590
    choice.DropDownStyle = ComboBoxStyle.DropDownList
    for role in roles:
        choice.Items.Add(role)
    # No preselected physical role: generic names do not identify a material.
    button = Button()
    button.Text = "OK"
    button.Left, button.Top = 510, 145
    button.DialogResult = DialogResult.OK
    dialog.Controls.Add(label)
    dialog.Controls.Add(choice)
    dialog.Controls.Add(button)
    dialog.AcceptButton = button
    try:
        if dialog.ShowDialog() != DialogResult.OK or choice.SelectedIndex < 0:
            raise Exception("Object mapping cancelled: " + object_name)
        return str(choice.SelectedItem)
    finally:
        dialog.Dispose()


def detect_material(name, imported_material):
    tokens = set(re.findall(r"[a-z0-9]+", name.lower()))
    material = imported_material.lower().strip('" ')
    candidates = set()
    if material == "copper" or tokens & set(["copper", "cu", "tx", "rx", "coil", "trace"]):
        candidates.add("copper")
    if material in ("fr4", "fr4_epoxy") or tokens & set(["fr4", "substrate", "dielectric"]):
        candidates.add("FR4_epoxy")
    if material == "c45" or tokens & set(["c45"]):
        candidates.add("C45")
    if material == "aluminum" or tokens & set(["aluminum", "aluminium", "al2024"]):
        candidates.add("aluminum")
    return list(candidates)[0] if len(candidates) == 1 else None


def populate_mapping(editor, solids, sheets):
    assigned = set(obj for objects in MATERIAL_OBJECTS.values() for obj in objects)
    for obj in solids:
        if obj in assigned:
            continue
        try:
            imported_material = str(editor.GetPropertyValue(
                "Geometry3DAttributeTab", obj, "Material"))
        except Exception:
            imported_material = ""
        role = detect_material(obj, imported_material)
        if role is None:
            role = choose_role(obj, ["copper", "FR4_epoxy", "C45", "aluminum"],
                "Select the actual material. Copper = PCB conductors; "
                "FR4 = substrate; C45 = steel; aluminum = aluminum specimen. "
                "If this is another part, cancel and configure its material separately.")
        MATERIAL_OBJECTS[role].append(obj)
        log("Material mapping: " + obj + " -> " + role)
    # Only terminal-labelled sheets are eligible for automatic terminal mapping.
    # Do not assign an arbitrary PCB face or every sheet as a coil cross-section.
    for sheet in sheets:
        if sheet in TX_TERMINAL_SHEETS + RX_TERMINAL_SHEETS:
            continue
        tokens = set(re.findall(r"[a-z0-9]+", sheet.lower()))
        terminal = bool(tokens & set(["terminal", "section", "cutsection"]))
        if terminal and "tx" in tokens and "rx" not in tokens:
            role = "TX terminal"
        elif terminal and "rx" in tokens and "tx" not in tokens:
            role = "RX terminal"
        else:
            role = choose_role(sheet, ["Unused sheet", "TX terminal", "RX terminal"],
                "Select TX/RX only for a conductor cross-section sheet. "
                "Use one section per independent conductor, not both ends.")
        if role == "TX terminal":
            TX_TERMINAL_SHEETS.append(sheet)
        elif role == "RX terminal":
            RX_TERMINAL_SHEETS.append(sheet)
    if not sheets and not TX_TERMINAL_SHEETS:
        raise Exception("CAD imported solids only. In Maxwell create a cross-section "
                        "sheet for TX; a terminal cannot be inferred from an arbitrary face. "
                        "Export/include the terminal sheet in the CAD input before rerunning.")


def frequency_points(start, stop, count):
    if any(math.isnan(float(v)) or math.isinf(float(v)) for v in (start, stop, count)):
        raise ValueError("Frequency settings must be finite")
    if start <= 0 or stop < start or count < 1 or int(count) != count:
        raise ValueError("Invalid frequency range/count")
    if count == 1:
        if start != stop:
            raise ValueError("One point requires identical start and stop")
        return [float(start)]
    return [start * (stop / float(start)) ** (i / float(count - 1))
            for i in range(int(count))]


def skin_depth_mm(frequency, relative_mu, conductivity):
    if min(frequency, relative_mu, conductivity) <= 0:
        raise ValueError("Skin-depth inputs must be positive")
    return 1000.0 / math.sqrt(math.pi * frequency *
                            (4e-7 * math.pi) * relative_mu * conductivity)


def insert_frequency_setups(analysis, frequencies):
    names = []
    for index, frequency in enumerate(frequencies):
        name = "Freq_" + str(index + 1).zfill(3)
        analysis.InsertSetup("EddyCurrent", [
            "NAME:" + name, "Enabled:=", True,
            "MaximumPasses:=", MAX_ADAPTIVE_PASSES,
            "MinimumPasses:=", 2, "MinimumConvergedPasses:=", 2,
            "PercentRefinement:=", 30,
            "PercentError:=", ADAPTIVE_PERCENT_ERROR,
            "SolveFieldOnly:=", False,
            "Frequency:=", "%.12gHz" % frequency,
            "HasSweepSetup:=", False])
        names.append(name)
    return names


def assign_winding(boundary, name, sheets, current, point_out):
    # Maxwell 3D transient: sheet coil terminals belong to a winding.
    boundary.AssignWindingGroup(
        ["NAME:" + name, "Type:=", "Current", "IsSolid:=", True,
         "Current:=", current, "Resistance:=", "0ohm",
         "Inductance:=", "0nH", "Voltage:=", "0V",
         "ParallelBranchesNum:=", "1"])
    terminals = []
    for index, sheet in enumerate(sheets):
        terminal = name + "_Terminal_" + str(index + 1)
        boundary.AssignCoilTerminal(
            ["NAME:" + terminal, "Objects:=", [sheet],
             "Conductor number:=", "1", "Point out of terminal:=", point_out])
        terminals.append(terminal)
    boundary.AddWindingTerminals(name, terminals)


# ------------------------- START AEDT -------------------------

try:
    import ScriptEnv
    ScriptEnv.Initialize("Ansoft.ElectronicsDesktop")
    oDesktop.RestoreWindow()
    oDesktop.AddMessage("", "", 0, "ECT script version: " + SCRIPT_VERSION)
    if SOLUTION_TYPE not in ("EddyCurrent", "Transient"):
        raise ValueError("Unsupported SOLUTION_TYPE")
    frequencies = frequency_points(SWEEP_START_HZ, SWEEP_STOP_HZ, SWEEP_POINTS)
    if min(FREQ_HZ, CURRENT_PEAK_A, COPPER_THICKNESS_MM,
           MESH_DIVISIONS_PER_SKIN_DEPTH, TRANSIENT_CYCLES,
           TRANSIENT_STEPS_PER_CYCLE) <= 0:
        raise ValueError("Frequency, current and copper thickness must be positive")
    highest_frequency = max(frequencies) if SOLUTION_TYPE == "EddyCurrent" else FREQ_HZ

    # Choose Parasolid file
    dlg = OpenFileDialog()
    dlg.Title = "Select printed ECT sensor Parasolid file"
    dlg.Filter = "Parasolid files (*.x_t;*.x_b)|*.x_t;*.x_b|All files (*.*)|*.*"
    dlg.Multiselect = False
    if dlg.ShowDialog() != DialogResult.OK:
        log("No geometry selected. Script stopped.")
        raise Exception("Geometry selection cancelled.")

    geometry_file = str(dlg.FileName)
    if not os.path.isfile(geometry_file):
        raise Exception("Geometry file not found: " + geometry_file)

    if os.path.splitext(geometry_file)[1].lower() not in (".x_t", ".x_b"):
        raise Exception("Select a Parasolid .x_t or .x_b file, not a renamed CAD file.")
    log("Geometry: " + geometry_file)

    # Create project/design
    oProject = oDesktop.NewProject()
    oProject.InsertDesign("Maxwell 3D", DESIGN_NAME, SOLUTION_TYPE, "")
    oDesign = oProject.SetActiveDesign(DESIGN_NAME)
    oEditor = oDesign.SetActiveEditor("3D Modeler")
    oEditor.SetModelUnits(
        ["NAME:Units Parameter", "Units:=", MODEL_UNITS, "Rescale:=", False]
    )

    # The native CAD importer takes SourceFile, not FileName. With FileName
    # the importer can receive an empty source and report unsupported format.
    try:
        oEditor.Import(
            ["NAME:NativeBodyParameters",
             "HealOption:=", 0,
             "Options:=", "",
             "FileType:=", "UnRecognized",
             "MaxStitchTol:=", -1,
             "ImportFreeSurfaces:=", True,
             "SourceFile:=", geometry_file])
    except Exception as import_error:
        log("CAD import failed: " + geometry_file)
        log("Try Modeler > Import with this same file in AEDT 2021 R1. "
            "If manual import also fails, check the CAD translator and "
            "re-export to a Parasolid version supported by your installation. "
            "Renaming the file extension does not convert the model.")
        raise
    log("Parasolid import command sent.")

    # List imported solids/sheets so object names can be mapped correctly.
    try:
        solid_names = list(oEditor.GetObjectsInGroup("Solids"))
    except:
        solid_names = []
    try:
        sheet_names = list(oEditor.GetObjectsInGroup("Sheets"))
    except:
        sheet_names = []

    log("Imported solid objects: " + ", ".join(solid_names))
    log("Imported sheet objects: " + ", ".join(sheet_names))

    # Refuse an incomplete model rather than solving unassigned imported bodies.
    if not solid_names:
        raise Exception("No solids imported. Check Parasolid version/units.")
    populate_mapping(oEditor, solid_names, sheet_names)
    if not MATERIAL_OBJECTS["copper"] or not (MATERIAL_OBJECTS["C45"] or MATERIAL_OBJECTS["aluminum"]):
        raise Exception("Mapping must include copper conductors and a C45 or aluminum specimen. "
                        "Check the selected roles and imported geometry.")
    if not TX_TERMINAL_SHEETS:
        raise Exception("No TX cross-section sheet selected. A valid TX terminal is required.")
    mapped = []
    for material, objects in MATERIAL_OBJECTS.items():
        for obj in objects:
            if obj not in solid_names:
                raise Exception("Material object is not an imported solid: " + obj)
            if obj in mapped:
                raise Exception("Object assigned to multiple materials: " + obj)
            mapped.append(obj)
    if set(TX_TERMINAL_SHEETS) & set(RX_TERMINAL_SHEETS):
        raise Exception("TX and RX must use separate terminals.")
    for sheet in TX_TERMINAL_SHEETS + RX_TERMINAL_SHEETS:
        if sheet not in sheet_names:
            raise Exception("Terminal sheet missing: " + sheet)
    if len(set(TX_TERMINAL_SHEETS + RX_TERMINAL_SHEETS)) != len(TX_TERMINAL_SHEETS + RX_TERMINAL_SHEETS):
        raise Exception("Duplicate terminal sheets.")
    unmapped = set(solid_names) - set(mapped)
    if unmapped:
        raise Exception("Map all imported solids before solving: " + ", ".join(sorted(unmapped)))

    # Local, explicit materials avoid reliance on installed library spelling.
    # Assumptions, not measured values from the slides. C45 remains linear.
    definitions = oProject.GetDefinitionManager()
    properties = {
        "copper": ("1", "5.8e7", "1"),
        "FR4_epoxy": ("1", "0", "4.4"),
        "C45": (C45_RELATIVE_MU, C45_CONDUCTIVITY, "1"),
        "aluminum": ("1", "3.5e7", "1")}
    for key, objects in MATERIAL_OBJECTS.items():
        if not objects:
            continue
        mu, sigma, epsilon = properties[key]
        material_name = "ECT_" + key
        definitions.AddMaterial([
            "NAME:" + material_name, "CoordinateSystemType:=", "Cartesian",
            "BulkOrSurfaceType:=", 1,
            ["NAME:PhysicsTypes", "set:=", ["Electromagnetic"]],
            "permeability:=", mu, "conductivity:=", sigma,
            "permittivity:=", epsilon])
        assign_material(oEditor, objects, material_name)

    # AEDT percentage padding uses numeric values and per-direction types.
    region_parameters = ["NAME:RegionParameters"]
    for direction in ("+X", "-X", "+Y", "-Y", "+Z", "-Z"):
        region_parameters.extend([
            direction + "PaddingType:=", "Percentage Offset",
            direction + "Padding:=", REGION_PADDING_PERCENT])
    oEditor.CreateRegion(region_parameters,
        ["NAME:Attributes", "Name:=", "Region", "Flags:=", "Wireframe#",
         "Color:=", "(143 175 143)", "Transparency:=", 0.9,
         "PartCoordinateSystem:=", "Global", "MaterialValue:=", '"air"',
         "SolveInside:=", True])

    oBoundary = oDesign.GetModule("BoundarySetup")
    if SOLUTION_TYPE == "EddyCurrent":
        if len(TX_TERMINAL_SHEETS) != 1:
            raise Exception("Frequency mode currently supports one TX conductor section. "
                            "Do not select both ends or multiple spiral turns.")
        oBoundary.AssignCurrent([
            "NAME:TX_Current", "Objects:=", TX_TERMINAL_SHEETS,
            "Current:=", str(CURRENT_PEAK_A) + "A", "Phase:=", "0deg",
            "IsSolid:=", True, "Point out of terminal:=", TX_POINT_OUT])
        if RX_TERMINAL_SHEETS:
            raise Exception("Frequency mode currently supports a single-coil impedance sensor. "
                            "RX voltage needs a separately validated open-circuit winding model; "
                            "use Transient mode or configure that model before solving.")
        oDesign.GetModule("MaxwellParameterSetup").AssignMatrix([
            "NAME:SensorMatrix", ["NAME:MatrixEntry",
             ["NAME:MatrixEntry", "Source:=", "TX_Current", "NumberOfTurns:=", "1"]],
            ["NAME:MatrixGroup"]])
    else:
        assign_winding(oBoundary, "TX_Winding", TX_TERMINAL_SHEETS,
            str(CURRENT_PEAK_A) + "A*sin(2*pi*" + str(FREQ_HZ) + "Hz*time)",
            TX_POINT_OUT)
        if RX_TERMINAL_SHEETS:
            assign_winding(oBoundary, "RX_Winding", RX_TERMINAL_SHEETS,
                           "0A", RX_POINT_OUT)
    # Include induced currents in copper and specimen for the solid model.
    eddy_settings = ["NAME:Eddy Effect Setting"]
    for obj in MATERIAL_OBJECTS["copper"] + MATERIAL_OBJECTS["C45"] + MATERIAL_OBJECTS["aluminum"]:
        eddy_settings.append(["NAME:Data", "Object Name:=", obj,
                              "Eddy Effect:=", True])
    oBoundary.SetEddyEffect(["NAME:Eddy Effect Setting Vector", eddy_settings])

    # ------------------------- MESH -------------------------
    oMesh = oDesign.GetModule("MeshSetup")

    copper_skin = skin_depth_mm(highest_frequency, 1.0, 5.8e7)
    copper_length = min(float(COPPER_MAX_LENGTH[:-2]),
                        COPPER_THICKNESS_MM / 2.0,
                        copper_skin / MESH_DIVISIONS_PER_SKIN_DEPTH)
    copper_mesh_length = "%.8gmm" % copper_length
    log("Highest frequency skin depth in copper: %.6g mm" % copper_skin)
    log("Copper volume mesh limit: " + copper_mesh_length)
    copper_mesh_objects = MATERIAL_OBJECTS["copper"]
    if copper_mesh_objects:
        oMesh.AssignLengthOp(
            ["NAME:PCB_Copper_Mesh",
             "RefineInside:=", True,
             "Objects:=", copper_mesh_objects,
             "RestrictElem:=", False,
             "RestrictLength:=", True,
             "MaxLength:=", copper_mesh_length]
        )
        log("Copper mesh operation assigned.")

    for key in ("C45", "aluminum"):
        if MATERIAL_OBJECTS[key]:
            mu, sigma, unused = properties[key]
            depth = skin_depth_mm(highest_frequency, float(mu), float(sigma))
            length = min(float(STEEL_MAX_LENGTH[:-2]),
                         depth / MESH_DIVISIONS_PER_SKIN_DEPTH)
            log(key + " skin depth: %.6g mm; volume mesh limit: %.6g mm" % (depth, length))
            oMesh.AssignLengthOp([
                "NAME:" + key + "_Mesh", "RefineInside:=", True,
                "Objects:=", MATERIAL_OBJECTS[key], "RestrictElem:=", False,
                "RestrictLength:=", True, "MaxLength:=", "%.8gmm" % length])

    # ------------------------- TRANSIENT SETUP -------------------------
    oAnalysis = oDesign.GetModule("AnalysisSetup")
    if SOLUTION_TYPE == "EddyCurrent":
        setup_names = insert_frequency_setups(oAnalysis, frequencies)
        log("Frequency sweep: " + ", ".join("%.8g Hz" % f for f in frequencies))
    else:
        setup_names = ["Setup1"]
        oAnalysis.InsertSetup(
            "Transient",
            ["NAME:Setup1",
             "Enabled:=", True,
             ["NAME:MeshLink", "ImportMesh:=", False],
             "NonlinearSolverResidual:=", "0.005",
             "ScalarPotential:=", "Second Order",
             "SmoothBHCurve:=", False,
             "StopTime:=", "%.12gs" % (float(TRANSIENT_CYCLES) / FREQ_HZ),
             "TimeStep:=", "%.12gs" % (1.0 / (TRANSIENT_STEPS_PER_CYCLE * FREQ_HZ)),
             "OutputError:=", False,
             "OutputPerObjectCoreLoss:=", False,
             "OutputPerObjectSolidLoss:=", False,
             "UseControlProgram:=", False,
             "ControlProgramName:=", "",
             "ControlProgramArg:=", "",
             "CallCtrlProgAfterLastStep:=", False,
             "FastReachSteadyState:=", False,
             "AutoDetectSteadyState:=", False,
             "SaveFieldsType:=", "Every N Steps",
             "NumberSolveSteps:=", 1,
             "RangeStart:=", "0s",
             "RangeEnd:=", "%.12gs" % (float(TRANSIENT_CYCLES) / FREQ_HZ)]
        )
        log("Transient setup created.")

    # Save project before solving.
    output_dir = OUTPUT_DIRECTORY or os.path.dirname(geometry_file)
    if not os.path.isdir(output_dir):
        raise Exception("Output directory does not exist: " + output_dir)
    project_file = os.path.join(output_dir, PROJECT_NAME + "_" +
                                datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".aedt")
    if os.path.exists(project_file):
        raise Exception("Output already exists; choose another PROJECT_NAME: " + project_file)
    oProject.SaveAs(project_file, False)
    log("Project saved: " + project_file)

    # ValidateDesign returns 1 for a successful validation in AEDT.
    validation_result = oDesign.ValidateDesign()
    if validation_result != 1:
        raise Exception("Validation failed (result=" + str(validation_result) +
                        "). Inspect AEDT Message Manager; solve blocked.")
    log("Design validation passed.")
    if AUTO_SOLVE:
        for setup_name in setup_names:
            oDesign.Analyze(setup_name)
        oProject.Save()
        log("Solver returned. Check convergence and solution messages in AEDT.")
    else:
        log("Saved, not solved. Inspect coil orientation, conductor continuity, "
            "lift-off, defect geometry and outer boundary before enabling AUTO_SOLVE.")
    if SOLUTION_TYPE == "EddyCurrent":
        log("Results: Results > Create EddyCurrent Report > Data Table; "
            "select SensorMatrix R/L for TX_Current for each Freq_* setup. "
            "Calculate Z = R + j*2*pi*f*L with L in henries. "
            "Compare defect/no-defect cases at identical frequencies.")
    log("Check adaptive convergence at EVERY frequency; reaching max passes is "
        "not convergence. Compare finer meshes and larger air regions. "
        "This is a magnetoquasistatic model; it omits PCB parasitic capacitance "
        "and self resonance. Use HFSS for resonant/full-wave behavior.")

except Exception as e:
    log("ERROR: " + str(e))
    log("The project may have been created partially. Check the Message Manager.")
    raise
