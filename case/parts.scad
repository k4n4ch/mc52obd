// genparts.py が生成。手で直さない。
module pcb_parts() {
  translate([px(6.35) - 5.10, py(7.62) - 1.25, PCB_TOP]) cube([10.20, 2.50, 3.0]);   // J1
  translate([px(9.25) - 2.15, py(37.11) - 1.30, PCB_TOP]) cube([4.30, 2.60, 3.0]);   // D1
  translate([px(15.04) - 1.80, py(35.23) - 2.30, PCB_TOP]) cube([3.60, 4.60, 3.0]);   // D2
  translate([px(6.63) - 1.27, py(28.98) - 1.52, PCB_TOP]) cube([2.54, 3.05, 3.0]);   // C1
  translate([px(9.75) - 0.38, py(28.98) - 0.76, PCB_TOP]) cube([0.76, 1.52, 3.0]);   // C3
  translate([px(9.48) - 0.76, py(24.86) - 0.38, PCB_TOP]) cube([1.52, 0.76, 3.0]);   // R8
  translate([px(13.61) - 2.00, py(28.98) - 2.00, PCB_TOP]) cube([4.00, 4.00, 3.0]);   // L1
  translate([px(2.74) - 0.76, py(32.77) - 0.38, PCB_TOP]) cube([1.52, 0.76, 3.0]);   // C6
  translate([px(17.63) - 0.64, py(28.98) - 1.02, PCB_TOP]) cube([1.27, 2.03, 3.0]);   // C4
  translate([px(20.24) - 0.64, py(28.98) - 1.02, PCB_TOP]) cube([1.27, 2.03, 3.0]);   // C5
  translate([px(7.80) - 0.38, py(17.27) - 0.76, PCB_TOP]) cube([0.76, 1.52, 3.0]);   // C7
  translate([px(10.11) - 0.38, py(17.27) - 0.76, PCB_TOP]) cube([0.76, 1.52, 3.0]);   // C8
  translate([px(13.06) - 0.76, py(18.06) - 0.38, PCB_TOP]) cube([1.52, 0.76, 3.0]);   // R7
  translate([px(16.69) - 0.76, py(17.96) - 0.38, PCB_TOP]) cube([1.52, 0.76, 3.0]);   // C12
  translate([px(11.00) - 0.76, py(22.38) - 0.38, PCB_TOP]) cube([1.52, 0.76, 3.0]);   // R5
  translate([px(14.63) - 0.76, py(22.28) - 0.38, PCB_TOP]) cube([1.52, 0.76, 3.0]);   // C11
  translate([px(3.17) - 1.02, py(22.12) - 0.64, PCB_TOP]) cube([2.03, 1.27, 3.0]);   // C9
  translate([px(7.37) - 0.76, py(22.28) - 0.38, PCB_TOP]) cube([1.52, 0.76, 3.0]);   // C10
  translate([px(18.26) - 0.76, py(22.38) - 0.38, PCB_TOP]) cube([1.52, 0.76, 3.0]);   // R3
  translate([px(21.84) - 0.76, py(22.38) - 0.38, PCB_TOP]) cube([1.52, 0.76, 3.0]);   // R4
  translate([px(20.32) - 0.76, py(18.06) - 0.38, PCB_TOP]) cube([1.52, 0.76, 3.0]);   // R6
  translate([px(2.74) - 1.45, py(28.98) - 0.80, PCB_TOP]) cube([2.90, 1.60, 3.0]);   // U1
  translate([px(34.04) - 9.00, py(23.37) - 12.75, PCB_TOP]) cube([18.00, 25.50, 3.1]);   // U2
  translate([px(3.73) - 2.45, py(15.29) - 1.95, PCB_TOP]) cube([4.90, 3.90, 3.0]);   // U3
  translate([px(31.50) - 7.60, py(7.62) - 1.25, PCB_TOP]) cube([15.20, 2.50, 3.0]);   // J2
  translate([px(15.82) - 3.15, py(13.21) - 3.15, PCB_TOP]) cube([6.30, 6.30, 8.0]);   // C2
}
