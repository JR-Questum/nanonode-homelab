# Compute - build log - It.1

## 3D Printed Faceplate & Thermal Validation

This first iteration focuses on designing and validating a 3D printed faceplate for the [[Compute Node Module]], with thermal testing to understand airflow characteristics and temperature behavior under load.

### Scope of This Iteration

- Design a rack-mountable faceplate in Fusion 360  
- Validate 3D printing process and settings  
- Test structural fit for standard 10" rack rails  
- Evaluate thermal performance with and without airflow obstruction  
- Establish baseline temperature data for future iterations  

### Hardware Used

- [[Hardware overview#Lenovo thinkcenter m720q|Lenovo ThinkCenter M720q]] 
- [[Power Delivery Module]] for power under test conditions  
- Bambu Lab H2D 3D printer  
- MEDICAT bootable USB with Windows 10 Mini for stress testing  

## Fusion 360 Design

### Dimensions

The faceplate was designed to the following specifications:

| Dimension | Value | Notes |
|-----------|-------|-------|
| Width | 254mm | Standard 1U (1/19" rack unit) |
| Height | 44.45mm | 1U standard |
| Depth | 189mm | Accommodates Lenovo M720q depth |

### Design Features
![[fusion360_compute_faceplate.jpg]]
The following features were incorporated into the design:

- Mounting holes positioned for standard rack rail compatibility
- Ventilation cutouts to allow airflow through the faceplate
- Insert cutout designed to accept removable panels for testing different airflow configurations

![[fusion360_compute_faceplate_blank_insert.jpg]]

The insert cutout was intentionally designed to accommodate future iterations where different materials and ventilation patterns can be swapped without reprinting the entire faceplate.

## 3D Printing Process

### Printer & Material

- Printer: Bambu Lab H2D
- Filament: PLA
- Color: Red

| Setting       | Value                         |
| ------------- | ----------------------------- |
| Layer height  | 0.2mm                         |
| Infill        | 15% adaptive cubic            |
| Supports      | Default tree support settings |
| Print time    | 2.9h                          |
| Material used | 71g                           |

## Faceplate Insert

### Current Iteration Approach

For this test iteration, the faceplate insert was partially printed using the same PLA filament as the faceplate itself. The insert fits into the designated cutout area designed into the faceplate.

![[3dprint_faceplate iteration1.gif]]
### Print Settings
### Planned Improvement

In future iterations, this insert will be replaced with a laser-cut wooden panel. This change will provide:

- Better aesthetic appearance matching the theme
- Easier iteration on ventilation patterns without reprinting the entire faceplate
- More professional finish

## Temperature Testing Methodology

### Test Environment

To validate thermal performance, the following test setup was used:

1. Compute node module configured as described in [[Compute Node Module]]
2. [[Power Delivery Module]] providing power to simulate real-world operating conditions
3. Windows 10 Mini via MEDICAT bootable USB for stress testing
4. AIDA64 stress test tool for CPU load generation

### Test Scenarios

| Open Airflow                                | Blocked airflow                          |
| ------------------------------------------- | ---------------------------------------- |
| ![[Node_faceplate_without_test_insert.jpg]] | ![[Node_faceplate_with_test_insert.jpg]] |

Tree scenarios were tested to understand the impact of airflow obstruction:

| Scenario          | Configuration                                                 | Purpose                        |
| ----------------- | ------------------------------------------------------------- | ------------------------------ |
| Open airflow Idle | Faceplate installed, insert removed (cutout open) - no load   | Baseline idle temperatures     |
| Open airflow      | Faceplate installed, insert removed (cutout open) - load test | Baseline thermal performance   |
| Blocked airflow   | Faceplate installed, insert in place - load test              | Worst-case thermal performance |

## Results

### Metrics collected

| Metric          | Idle   | Open airflow | Blocked airflow |
| --------------- | ------ | ------------ | --------------- |
| Core #1 temp    | 37     | 77           | 78              |
| Core #2 temp    | 37     | 77           | 77              |
| Core #3 temp    | 36     | 77           | 77              |
| Core #4 temp    | 36     | 76           | 76              |
| CPU Package     | 1.37w  | 36.54w       | 36,59w          |
| CPU voltage     | 0.660v | 1.050v       | 1.047v          |
| CPU clock       | 798    | 3191         | 3191            |
| Core #1 clock   | 798    | 3191         | 3191            |
| Core #2 clock   | 798    | 3191         | 3191            |
| Core #3 clock   | 798    | 3191         | 3191            |
| Core #4 clock   | 798    | 3191         | 3191            |
| Core #5 clock   | 798    | 3191         | 3191            |
| Core #6 clock   | 798    | 3191         | 3191            |
| CPU utilization | 0      | 100          | 100             |
| CPU throttling  | 0      | 0            | 0               |

### Observations

I was pleasantly surprised that there was barely a difference between the temperatures of blocked vs open airflow. Because these are second hand nodes there is a possibility that there is still some dust in the fans. During this test the node pulled a maximum between 55 and 58 watts of power.
## Key Learnings

1. 3D printing workflow validated: The Fusion 360 design translated well to physical print with Bambu Lab H2D
2. PLA is suitable for prototyping: While not ideal for final production (due to heat resistance), PLA worked well for this validation phase
3. Insert cutout design proves useful: The ability to swap inserts without reprinting the faceplate will accelerate future testing
4. Airflow obstruction has measurable impact: No noticeable temp differences

