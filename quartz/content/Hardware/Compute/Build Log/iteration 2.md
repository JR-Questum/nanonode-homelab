# Compute - build log - It.2

## Laser-Cut Frontplate

The laser-cut frontplate is a decorative and identification panel for the compute node enclosures in the [[Compute Node Module]].

Rather than leaving the factory frontpanel of the [[Hardware overview#Lenovo thinkcenter m720q|Lenovo m720q]] chassis fully exposed, this design introduces a custom laser-cut faceplate mounted into a 3D-printed holder. Each frontplate features a Nier:Automata-themed design with engraved node identification, including POD numbers and MAC addresses.

The goal is to provide visual consistency across all compute nodes while maintaining clear node-level identification from the front of the rack.

## Goals

The frontplate design is driven by the following objectives:

- provide a unified aesthetic theme across all compute nodes
- display node identification (POD number) on the frontplate
- display network identification (MAC address) on the right side of the frontplate
- maintain compatibility with the existing [[Hardware overview#Lenovo thinkcenter m720q|m720q]] chassis form factor
- use laser cutting and engraving manufacturing

## Design Approach

### Thematic consistency

All frontplates follow the same Nier:Automata-inspired visual design The decorative elements are identical between nodes, with only the identification text varying per unit.

### Functional identification

Each frontplate clearly displays:
- the assigned POD number (primary identifier)
- the MAC address (secondary identifier, right side)

This allows quick visual identification of nodes without requiring remote access or label stickers.

### Mounting

The frontplate fits into the 3D-printed holder that holds to the [[Hardware overview#Lenovo thinkcenter m720q|m720q]] chassis in the final version the laser cutted wood and 3d-printed holder will be glued together.  While the ventilation hole positions do not perfectly match the physical chassis, temperature testing confirmed that blocking certain ventilation openings has negligible impact on thermal performance.

## Material Specifications

The frontplate is fabricated from the following material:

- **Source material**: IKEA BESTA backboard (laminated particleboard)
- **Dimensions**: 200mm × 33mm
- **Thickness**: 2.9mm
- **Surface**: Laminated finish (allows white engrave effect via lamination/glue exposure)

## Manufacturing Process

### Equipment

Laser cutting and engraving is performed using:
- **Device**: Bambu Lab H2D
- **Module**: 40W laser module

### Calibration

Prior to the test cuts, a laser calibration sheet is generated to verify engraving and cutting parameters for this backboard. 

![[Node_faceplate_laser_test.jpg]]

### White Engraving Effect

A notable characteristic of this material is the ability to produce white engraved areas. This effect is believed to result from exposing the backing layer of the lamination or the underlying adhesive. This behavior is leveraged as an additional engraving color option in the frontplate design.

### Engraving and Cutting Parameters

The design uses color-coded layers in the render file, each mapped to specific laser parameters:
![[Node_faceplate_inkscape_design.jpg]]

| Render Color | Operation | Speed | Power |
|-------------|-----------|-------|-------|
| Red | Cut | 5 mm/s | 50% |
| Yellow | Black engraving | 120 mm/s | 60% |
| Blue | Brown engraving | 196 mm/s | 38% |
| Green | White engraving | 348 mm/s | 16% |

## Design Workflow

The frontplate design follows this workflow:

1. **3D modeling** — Create the base layout and hole pattern in Fusion 360, based on the previous test printed faceplate.
2. **DXF export** — Export the design from Fusion 360 in DXF format for vector editing.
3. **Vector design** — Import the DXF into Inkscape and apply the Nier:Automata-themed decorative elements, color-coded for laser operations.
4. **Laser processing** — Send the final design to the Bambu Lab H2D for cutting and multi-color engraving.

![[Node_faceplate_laser_insert.jpg]]

## Current Deployment

The initial iteration produced a single test frontplate, which was successfully fitted into the 3D-printed holder on the first attempt.

Planned production includes three frontplates for the following nodes:
- POD 042
- POD 153
- POD 006

MAC addresses for the right-side engraving on each unit still need to be collected and applied to the respective designs.

## Results

![[Node_faceplate_without_node.jpg]]

![[Node_faceplate_with_node.jpg]]
