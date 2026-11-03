# -*- coding: utf-8 -*-
# ANSYS Electronics Desktop 2021 R1 - Maxwell 3D Transient
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
import System
import clr

clr.AddReference("System.Windows.Forms")
from System.Windows.Forms import (OpenFileDialog, DialogResult, Form, Label,
                                  ComboBox, ComboBoxStyle, Button)

# ------------------------- USER SETTINGS -------------------------

PROJECT_NAME = "Printed_ECT_Maxwell"
DESIGN_NAME = "ECT_PCB_Transient"

MODEL_UNITS = "mm"

# Example excitation settings; replace with measured operating conditions.
FREQ_HZ = 100000.0
CURRENT_PEAK_A = 0.1
STOP_TIME = "50us"       # 5 cycles at 100 kHz
TIME_STEP = "0.1us"      # 100 time steps per cycle
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
    "C45": []
}

# Coil terminal must be a SHEET created by cutting the TX copper conductor
# across its cross-section. Add the exact sheet name(s) here.
# Example: TX_TERMINAL_SHEETS = ["TX_CutSection"]
TX_TERMINAL_SHEETS = []

# Initial mesh limits only. Resolve actual copper thickness and specimen skin
# depth with a convergence study; 0.50 mm in steel may be too coarse at 100 kHz.
COPPER_MAX_LENGTH = "0.10mm"
STEEL_MAX_LENGTH = "0.50mm"

# Region padding around imported sensor/specimen geometry.
REGION_PADDING_PERCENT = 100
# Check boundary-distance and mesh convergence before using numerical results.

# ------------------------- HELPERS -------------------------

def log(message):
    print("[ECT SETUP] " + str(message))

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
    if material == "c45" or tokens & set(["c45", "specimen", "sample"]):
        candidates.add("C45")
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
            role = choose_role(obj, ["copper", "FR4_epoxy", "C45"],
                "Select the actual material. Copper = PCB conductors; "
                "FR4 = substrate; C45 = steel specimen. "
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
    oProject.InsertDesign("Maxwell 3D", DESIGN_NAME, "Transient", "")
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
    if not MATERIAL_OBJECTS["copper"] or not MATERIAL_OBJECTS["C45"]:
        raise Exception("Mapping must include copper conductors and a C45 specimen. "
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

    definitions = oProject.GetDefinitionManager()
    if not definitions.DoesMaterialExist("C45"):
        definitions.AddMaterial(
            ["NAME:C45", "CoordinateSystemType:=", "Cartesian",
             "BulkOrSurfaceType:=", 1,
             ["NAME:PhysicsTypes", "set:=", ["Electromagnetic"]],
             "permeability:=", C45_RELATIVE_MU,
             "conductivity:=", C45_CONDUCTIVITY])
    for material in ("copper", "FR4_epoxy"):
        if MATERIAL_OBJECTS[material] and not definitions.DoesMaterialExist(material):
            raise Exception("Required material unavailable in project/library: " + material)

    # Assign materials only to explicitly configured objects.
    assign_material(oEditor, MATERIAL_OBJECTS["copper"], "copper")
    assign_material(oEditor, MATERIAL_OBJECTS["FR4_epoxy"], "FR4_epoxy")
    assign_material(oEditor, MATERIAL_OBJECTS["C45"], "C45")

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
    assign_winding(oBoundary, "TX_Winding", TX_TERMINAL_SHEETS,
        str(CURRENT_PEAK_A) + "A*sin(2*pi*" + str(FREQ_HZ) + "Hz*time)",
        TX_POINT_OUT)
    if RX_TERMINAL_SHEETS:
        # Zero net current models an unloaded pickup, not a short circuit.
        assign_winding(oBoundary, "RX_Winding", RX_TERMINAL_SHEETS,
                       "0A", RX_POINT_OUT)
    else:
        log("RX not configured: excitation/field model only; no pickup voltage.")
    # Include induced currents in copper and specimen for the solid model.
    eddy_settings = ["NAME:Eddy Effect Setting"]
    for obj in MATERIAL_OBJECTS["copper"] + MATERIAL_OBJECTS["C45"]:
        eddy_settings.append(["NAME:Data", "Object Name:=", obj,
                              "Eddy Effect:=", True])
    oBoundary.SetEddyEffect(["NAME:Eddy Effect Setting Vector", eddy_settings])

    # ------------------------- MESH -------------------------
    oMesh = oDesign.GetModule("MeshSetup")

    copper_mesh_objects = MATERIAL_OBJECTS["copper"]
    if copper_mesh_objects:
        oMesh.AssignLengthOp(
            ["NAME:PCB_Copper_Mesh",
             "RefineInside:=", True,
             "Objects:=", copper_mesh_objects,
             "RestrictElem:=", False,
             "RestrictLength:=", True,
             "MaxLength:=", COPPER_MAX_LENGTH,
             "ApplyToInitialMesh:=", True]
        )
        log("Copper mesh operation assigned.")

    steel_mesh_objects = MATERIAL_OBJECTS["C45"]
    if steel_mesh_objects:
        oMesh.AssignLengthOp(
            ["NAME:C45_Mesh",
             "RefineInside:=", True,
             "Objects:=", steel_mesh_objects,
             "RestrictElem:=", False,
             "RestrictLength:=", True,
             "MaxLength:=", STEEL_MAX_LENGTH,
             "ApplyToInitialMesh:=", True]
        )
        log("C45 mesh operation assigned.")

    # ------------------------- TRANSIENT SETUP -------------------------
    oAnalysis = oDesign.GetModule("AnalysisSetup")
    oAnalysis.InsertSetup(
        "Transient",
        ["NAME:Setup1",
         "Enabled:=", True,
         ["NAME:MeshLink", "ImportMesh:=", False],
         "NonlinearSolverResidual:=", "0.005",
         "ScalarPotential:=", "Second Order",
         "SmoothBHCurve:=", False,
         "StopTime:=", STOP_TIME,
         "TimeStep:=", TIME_STEP,
         "OutputError:=", False,
         "OutputPerObjectCoreLoss:=", False,
         "OutputPerObjectSolidLoss:=", False,
         "UseControlProgram:=", False,
         "ControlProgramName:=", "",
         "ControlProgramArg:=", "",
         "CallCtrlProgAfterLastStep:=", False,
         "FastReachSteadyState:=", False,
         "AutoDetectSteadyState:=", False,
         "IsGeneralTransient:=", True,
         "IsHalfPeriodicTransient:=", False,
         "SaveFieldsType:=", "Every N Steps",
         "NumberSolveSteps:=", 1,
         "RangeStart:=", "0s",
         "RangeEnd:=", STOP_TIME,
         "ContinuumAir:=", False]
    )
    log("Transient setup created.")

    # Save project before solving.
    output_dir = OUTPUT_DIRECTORY or os.path.dirname(geometry_file)
    if not os.path.isdir(output_dir):
        raise Exception("Output directory does not exist: " + output_dir)
    project_file = os.path.join(output_dir, PROJECT_NAME + ".aedt")
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
        oDesign.Analyze("Setup1")
        oProject.Save()
        log("Solver returned. Check convergence and solution messages in AEDT.")
    else:
        log("Saved, not solved. Inspect coil orientation, conductor continuity, "
            "lift-off, defect geometry and outer boundary before enabling AUTO_SOLVE.")
    log("For RX use induced winding voltage versus time; compare identical "
        "defect/no-defect cases after startup transients decay. Check mesh, "
        "time-step and air-region convergence. C45 uses constant mu only.")

except Exception as e:
    log("ERROR: " + str(e))
    log("The project may have been created partially. Check the Message Manager.")
    raise
