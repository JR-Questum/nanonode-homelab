# Compute - build log - It.3

## Rack Build & Production Faceplates

The previous two iterations produced a faceplate design and a laser-cut frontplate, but there was nothing to actually mount them in. This iteration builds the rack itself and prints the production faceplates to go in it.

### Scope of This Iteration

- Print and assemble a 6U 10" rack frame
- Reprint the [[Hardware/Compute/Build Log/iteration 1|node faceplates]] in production filament
- Mount all three [[Hardware overview#Lenovo thinkcenter m720q|M720q]] nodes in the rack
- Establish the final rack layout alongside the [[Power Delivery Module]]

### Hardware Used

- **MOD 10** 10" rack design (printed parts)
- M3 bolts and cage nuts
- **[[Hardware overview#Lenovo thinkcenter m720q|Lenovo ThinkCenter M720q]]** ×3
- Bambu Lab H2D 3D printer

## The Rack

### Design Source

Rather than designing a rack from scratch, this build uses the **MOD 10** 10" rack design. It is a well-established printable rack system, and there was no good reason to reinvent it, the interesting engineering in this project lives in the modules that go *into* the rack, not the frame holding them.

The frame was built out to **6U**, which gives enough room for the three compute nodes, the [[Power Delivery Module]], the keystone and the [[Hardware overview#Ubiquiti UniFi USW Flex 2.5G 5|USW Flex 2.5G 5 switch]].

### Print Settings

The rack parts were printed in the same white ASA used for the [[Power Delivery/Build Log/iteration 4|1U power delivery chassis]]:

| Setting | Value |
|---------|-------|
| Nozzle | 0.4mm |
| Layer height | 0.2mm |
| Walls | 4 |
| Top / bottom layers | 6 |
| Infill | 40% gyroid |
| Material | ASA |
| Supports | Tree |

Printing went smoothly across all the parts, no warping, no failed plates, no reprints.

| ![[3dprint_MOD10_1.gif]] | ![[3dprint_MOD10_2.gif]] |
| ------------------------ | ------------------------ |

### Assembly

The frame goes together with M3 bolts and cage nuts. Assembly was uneventful, everything lined up and bolted together without any fettling required.

![[Compute_rack_frame_assembled.jpg]]

## Production Faceplates

### From Test Filament to Production Filament

The faceplate from [[Hardware/Compute/Build Log/iteration 1|It.1]] was printed in red PLA purely as test filament, and one of the key learnings from that iteration was that PLA is fine for prototyping but not what you want in a final build.

The production faceplates are therefore printed in the same white ASA as the rack, which also brings the compute nodes visually in line with the rest of the build.

![[3dprint_faceplate final.gif]]

![[Node_faceplate_asa_print_top.jpg]]


## Results

All three nodes are mounted in the rack in their final positions, with the [[Power Delivery Module]] planned sitting below them.

![[Compute_rack_nodes_mounted.jpg]]

This is the first iteration where the project actually looks like a rack 