# Power delivery - build log - It.4

## 1U Chassis Design, Print & Module Wiring

This iteration takes everything that has been living loose on the bench since [[iteration 3|It.3]] and gives it an actual home. Three parts to it: designing the 1U chassis in Fusion 360, printing it, and wiring the module up inside it.

### Scope of This Iteration

- Design a single-piece 1U chassis in Fusion 360
- Provide mounting for the [[Hardware overview#Meanwell UHP-350-24 Power Supply|UHP-350-24]], the prefboard, and the three PD modules
- Cut out a front panel for the screen, three buttons, and a laser-cut design insert
- Print the chassis on the Bambu Lab H2D in ASA
- Wire the full power path from mains through to the USB-C outputs

### Chassis Design

The chassis was modelled in Fusion 360 as a single piece. Everything mounts into it directly, no sub-brackets or separate trays:

- screw holes for the [[Hardware overview#Meanwell UHP-350-24 Power Supply|UHP-350-24]] power supply
- standoffs for the prefboard built in [[iteration 3|It.3]]
- three holders for the [[Power Delivery Module#USB-C PD output per node|USB-C PD modules]]

![[fusion360_Power_delivery_faceplate.jpg]]

The entire layout was driven by the 1U constraint. Component placement wasn't a matter of what looked tidy, it was a matter of what fit in the height available and still left room to route wiring between the sections.

#### Front Panel

The front panel carries:

- a cutout for the [[Hardware overview#1.69" TFT LCD (ST7789)|1.69" display]]
- three button openings
- three holders for the USB-C outputs
- a recessed cutout for a laser-cut design piece, matching the approach used on the [[Hardware/Compute/Build Log/iteration 2|compute node frontplates]]

### Printing

The chassis was printed on the Bambu Lab H2D with the following settings:

| Setting | Value |
|---------|-------|
| Nozzle | 0.4mm |
| Layer height | 0.2mm |
| Walls | 4 |
| Top / bottom layers | 6 |
| Infill | 40% gyroid |
| Material | ASA |
| Supports | Tree |

Before committing to the full print, a series of test prints were done on isolated sections of the model, mainly the mounting points and the front panel cutouts, to confirm the fittings were correct. Printing a small section to check a screw hole is a lot cheaper than discovering the problem at the end of a full-chassis print.

Once the fittings checked out, the chassis was printed in one go as a single part. The full print took **8h52m26s** and used **178g** of ASA.

![[3dprint_power_delivery_final.gif]]

![[Power_delivery_3d_printed_case.jpg]]

### Wiring

With the chassis printed, the module was wired up inside it. The power flow follows the architecture laid out in the [[Power Delivery Module#Power Path|module design]]:

```text
mains ──> UHP-350-24 ──> fuse ──> button ──> INA228 ──> USB-C PD module ──> node
```

#### Fuses & Buttons

Each branch gets its own fuse and its own front-panel button, sitting between the DC bus and the rest of the branch. That combination provides both fault isolation and per-node manual control.

![[Power_delivery_wiring_buttons_fuses.jpg]]

#### USB-C PD Outputs

At the far end of each branch is a USB-C PD module, mounted in the three holders designed into the chassis. Keeping one module per output means each node negotiates its own PD contract independently.

![[Power_delivery_wiring_PD_modules.jpg]]

#### Power Monitoring

Between the button and the PD module, each branch passes through its [[Hardware overview#INA228 – Power monitor|INA228]] on the [[iteration 3|prefboard]], so every node gets measured individually rather than only seeing total rack draw.

![[Power_delivery_wiring_Prefboard.jpg]]

#### Power Supply Input

Feeding all of this is the [[Hardware overview#Meanwell UHP-350-24 Power Supply|UHP-350-24]], which takes mains in and supplies the internal 24V DC bus that every branch taps off.

![[Power_delivery_wiring_UHP.jpg]]

### Results

Nothing particularly dramatic happened during this iteration, which is arguably the point, the power path had already been worked out and validated across the previous three iterations, so this was mostly a matter of executing on decisions that were already made.

![[Power_delivery_wiring_finished_front.jpg]]

The module now exists as an actual 1U unit rather than a pile of components on a bench.
