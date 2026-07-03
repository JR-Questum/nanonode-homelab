# Power delivery - build log - It.3

## Prefboard Assembly & INA228 Addressing

This iteration moves the build off the breadboard and onto something a bit more permanent. For reasons that made sense at the time, prefboard soldering was chosen over an actual PCB design.

### Scope of This Iteration

- Solder the [[Power Delivery Module#Power measurement|INA228]] sensors and support wiring onto prefboard
- Set unique I2C addresses on two of the three INA228 devices
- Validate all three sensors with an I2C scan on the ESP32
- Wire the I2C bus to the ESP32
- Add a header-based connection for the display
- Mount the ESP32 and wire up the buck converter

### Hardware Used

- **[[Hardware overview#INA228 – Power monitor|INA228 Current Sensor]]** ×3
- **[[Hardware overview#ESP‑32S – Monitoring Controller|ESP‑32S]]**
- **[[Hardware overview#1.69" TFT LCD (ST7789)|1.69" TFT LCD IPS display module]]**
- Prefboard, headers, and a buck converter

### INA228 Address Configuration

With three INA228 sensors sharing the same I2C bus, each one needs its own address. One device was left on its default address, and the A0/A1 pins on the other two were resoldered to shift their addresses:

```text
A0 - 0 | A1 - 0 = 0x40
A0 - 1 | A1 - 0 = 0x41
A0 - 0 | A1 - 1 = 0x44
```

### I2C Scan & Validation

Once the addressing was sorted, a simple I2C scan program was flashed to the ESP32 to confirm all three boards were alive and answering on the expected addresses.

Two out of three came back immediately. The third didn't show up at all. A closer look at the board revealed that only one of the two I2C pads was actually soldered, classic AliExpress quality control.

![[Power_delivery_faulty_solder_pad.jpg]]

Once that pad was fixed, all three sensors showed up correctly on the bus.

![[Power_delivery_i2c_soldered.jpg]]

### Wiring to the ESP32

With all three sensors validated, the I2C lines were wired over to the ESP32.

![[Power_delivery_i2c_wiring.jpg]]

### Display Header Wiring

Rather than soldering the display directly to the board, a header-based connection was used so the screen can be unplugged separately if it ever needs to be swapped or serviced.

![[Power_delivery_display_header.jpg]]

### Mounting the ESP32

The ESP32 was soldered in place on the prefboard next.

![[Power_delivery_esp32_mounted.jpg]]

### Buck Converter Wiring

Lastly, a buck converter was soldered in to step down the supply voltage and power the board.

![[Power_delivery_buck_converter.jpg]]

### Current State

All three INA228 sensors are addressed, wired, and responding correctly on the I2C bus, the ESP32 is mounted, and the board now has its own regulated 5V supply via the buck converter. The wiring is functional, if a bit improvised, but it will do 