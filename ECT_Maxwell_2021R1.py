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
# 3) Edit MATERIAL_OBJECTS and TX_TERMINAL_SHEETS below to match your geometry.
# 4) The PPT does not contain the lab pulse data file or its numerical values.
#    This script therefore uses a 100 kHz sinusoidal current as a starting point.
#    Replace it with your measured/current waveform when that data is available.

import os
import System
import clr

clr.AddReference("System.Windows.Forms")
from System.Windows.Forms import OpenFileDialog, DialogResult

# ------------------------- USER SETTINGS -------------------------

PROJECT_NAME = "Printed_ECT_Maxwell"
DESIGN_NAME = "ECT_PCB_Transient"

MODEL_UNITS = "mm"

# Starting excitation settings (not values specified in the PPT).
FREQ_HZ = 100000.0
CURRENT_PEAK_A = 0.1
STOP_TIME = "50us"       # 5 cycles at 100 kHz
TIME_STEP = "0.1us"      # 100 time steps per cycle

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

# Mesh length limits; refine further if the PCB trace width is below 0.25 mm.
COPPER_MAX_LENGTH = "0.10mm"
STEEL_MAX_LENGTH = "0.50mm"

# Region padding around imported sensor/specimen geometry.
REGION_PADDING = "100%"

# ------------------------- HELPERS -------------------------

def log(message):
    print("[ECT SETUP] " + str(message))

def assign_material(editor, object_names, material_name):
    if not object_names:
        log("SKIP material " + material_name + ": no object names configured.")
        return
    for obj in object_names:
        editor.AssignMaterial(
            ["NAME:Selections",
             "AllowRegionDependentPartSelectionForPMLCreation:=", True,
             "AllowRegionSelectionForPMLCreation:=", True,
             "Selections:=", obj],
            ["NAME:Attributes",
             "MaterialValue:=", material_name,
             "SolveInside:=", True,
             "ShellElement:=", False,
             "ShellElementThickness:=", "nan",
             "IsMaterialEditable:=", True,
             "UseMaterialAppearance:=", False,
             "IsLightweight:=", False]
        )
        log("Assigned " + material_name + " -> " + obj)

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

    geometry_file = dlg.FileName
    if not os.path.isfile(geometry_file):
        raise Exception("Geometry file not found: " + geometry_file)

    log("Geometry: " + geometry_file)

    # Create project/design
    oProject = oDesktop.NewProject()
    oProject.InsertDesign("Maxwell 3D", DESIGN_NAME, "Transient", "")
    oDesign = oProject.SetActiveDesign(DESIGN_NAME)
    oEditor = oDesign.SetActiveEditor("3D Modeler")
    oEditor.SetModelUnits(
        ["NAME:Units Parameter", "Units:=", MODEL_UNITS, "Rescale:=", False]
    )

    # Import Parasolid. Parasolid is supported by Maxwell 3D.
    # If your 2021 R1 installation records a different import argument
    # structure, use Record Script while importing the same .x_t once and
    # replace this Import call with the recorded command.
    oEditor.Import(
        ["NAME:NativeBodyParameters",
         "FileName:=", geometry_file]
    )
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

    # Define C45 material if not already present.
    # Copper and FR4_epoxy are commonly available in the AEDT material library.
    try:
        oProject.GetDefinitionManager().AddMaterial(
            ["NAME:C45",
             "permeability:=", C45_RELATIVE_MU,
             "conductivity:=", C45_CONDUCTIVITY,
             "mass_density:=", "7850kg_per_m3"]
        )
        log("Created material C45.")
    except:
        log("C45 may already exist; continuing.")

    # Assign materials only to explicitly configured objects.
    assign_material(oEditor, MATERIAL_OBJECTS["copper"], "copper")
    assign_material(oEditor, MATERIAL_OBJECTS["FR4_epoxy"], "FR4_epoxy")
    assign_material(oEditor, MATERIAL_OBJECTS["C45"], "C45")

    # Create surrounding air region. If the imported Parasolid already
    # contains a region, comment this block to avoid a duplicate region.
    try:
        oEditor.CreateRegion(
            ["NAME:RegionParameters",
             "XPos:=", REGION_PADDING, "XNeg:=", REGION_PADDING,
             "YPos:=", REGION_PADDING, "YNeg:=", REGION_PADDING,
             "ZPos:=", REGION_PADDING, "ZNeg:=", REGION_PADDING,
             "WhichAxis:=", "Z",
             "Type:=", "Percentage Offset",
             "XScale:=", 1,
             "YScale:=", 1,
             "ZScale:=", 1]
        )
        log("Created surrounding region.")
    except Exception as region_error:
        log("Region creation skipped/failed: " + str(region_error))
        log("Check whether an air region is already present in the imported geometry.")

    # ------------------------- TX WINDING -------------------------
    # A coil terminal in Maxwell 3D is assigned to a cross-section SHEET,
    # not to the entire copper trace solid.
    if TX_TERMINAL_SHEETS:
        for terminal_sheet in TX_TERMINAL_SHEETS:
            if terminal_sheet not in sheet_names:
                raise Exception("TX terminal sheet not found: " + terminal_sheet)

        oBoundary = oDesign.GetModule("BoundarySetup")
        oBoundary.AssignWindingGroup(
            ["NAME:TX_Winding",
             "Type:=", "Current",
             "IsSolid:=", True,
             "Current:=", str(CURRENT_PEAK_A) + "A*sin(2*pi*" +
                              str(FREQ_HZ) + "Hz*time)",
             "Resistance:=", "0ohm",
             "Inductance:=", "0nH",
             "Voltage:=", "0V",
             "ParallelBranchesNum:=", "1"]
        )

        terminal_names = []
        for index, terminal_sheet in enumerate(TX_TERMINAL_SHEETS):
            terminal_name = "TX_Terminal_" + str(index + 1)
            terminal_names.append(terminal_name)
            oBoundary.AssignCoilTerminalGroup(
                [terminal_name],
                ["NAME:" + terminal_name,
                 "Objects:=", [terminal_sheet],
                 "Conductor number:=", "1",
                 "Point out of terminal:=", False]
            )

        # Add the created terminals to the TX winding.
        boundary_items = ["NAME:BoundaryList"]
        for terminal_name in terminal_names:
            boundary_items.append(
                ["NAME:" + terminal_name,
                 "Point out of terminal:=", False,
                 "Conductor number:=", "1",
                 "Winding:=", "TX_Winding"]
            )
        oBoundary.AddTerminalsToWinding(
            ["NAME:AddTerminalsToWinding", boundary_items]
        )
        log("TX winding and coil terminal(s) assigned.")
    else:
        log("TX winding NOT assigned: TX_TERMINAL_SHEETS is empty.")
        log("Create a cross-section sheet through the TX copper and add its name to TX_TERMINAL_SHEETS.")

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
    output_dir = os.path.dirname(geometry_file)
    project_file = os.path.join(output_dir, PROJECT_NAME + ".aedt")
    oProject.SaveAs(project_file, True)
    log("Project saved: " + project_file)

    # Validate and solve only when the TX terminal and specimen mapping are
    # configured. This avoids launching an incomplete physical model.
    oDesign.ValidateDesign()
    log("Design validation command completed.")

    if TX_TERMINAL_SHEETS and MATERIAL_OBJECTS["C45"]:
        log("Starting Analyze Setup1...")
        oDesign.Analyze("Setup1")
        log("Analyze command completed.")
        oProject.Save()
        log("Project saved after solve.")
    else:
        log("SOLVE SKIPPED: configure TX_TERMINAL_SHEETS and MATERIAL_OBJECTS['C45'] first.")
        log("Also confirm that a C45 specimen with the intended defect is present in the geometry.")
        oProject.Save()

except Exception as e:
    log("ERROR: " + str(e))
    log("The project may have been created partially. Check the Message Manager.")
    raise
