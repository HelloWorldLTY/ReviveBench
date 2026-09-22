#!/usr/bin/env python3
"""Emit the hidden RTL design set, the flip-flop cell library, and a port manifest.

The manifest is what the verifier uses to build testbenches, so the verifier never has to
parse Verilog itself.

usage: make_designs.py
"""
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "designs"

CELLS = """// Flip-flop cell library. Both the reference RTL flow and the candidate netlist use these.
module DFF (output reg Q, input D, input CLK);
  initial Q = 1'b0;
  always @(posedge CLK) Q <= D;
endmodule
"""

DESIGNS = {}

DESIGNS["adder8"] = dict(seq=False, src="""
module adder8(input [7:0] a, input [7:0] b, input cin, output [7:0] sum, output cout);
  wire [8:0] t;
  assign t = a + b + cin;
  assign sum = t[7:0];
  assign cout = t[8];
endmodule
""", inputs=[("a", 8), ("b", 8), ("cin", 1)], outputs=[("sum", 8), ("cout", 1)])

DESIGNS["alu4"] = dict(seq=False, src="""
module alu4(input [3:0] a, input [3:0] b, input [2:0] op, output reg [3:0] y, output zero);
  always @(*) begin
    case (op)
      3'd0: y = a + b;
      3'd1: y = a - b;
      3'd2: y = a & b;
      3'd3: y = a | b;
      3'd4: y = a ^ b;
      3'd5: y = ~a;
      3'd6: y = a << 1;
      default: y = a >> 1;
    endcase
  end
  assign zero = (y == 4'd0);
endmodule
""", inputs=[("a", 4), ("b", 4), ("op", 3)], outputs=[("y", 4), ("zero", 1)])

DESIGNS["mux8x4"] = dict(seq=False, src="""
module mux8x4(input [31:0] din, input [2:0] sel, output reg [3:0] y);
  always @(*) begin
    case (sel)
      3'd0: y = din[3:0];
      3'd1: y = din[7:4];
      3'd2: y = din[11:8];
      3'd3: y = din[15:12];
      3'd4: y = din[19:16];
      3'd5: y = din[23:20];
      3'd6: y = din[27:24];
      default: y = din[31:28];
    endcase
  end
endmodule
""", inputs=[("din", 32), ("sel", 3)], outputs=[("y", 4)])

DESIGNS["prioenc8"] = dict(seq=False, src="""
module prioenc8(input [7:0] req, output reg [2:0] grant, output valid);
  always @(*) begin
    if (req[7]) grant = 3'd7;
    else if (req[6]) grant = 3'd6;
    else if (req[5]) grant = 3'd5;
    else if (req[4]) grant = 3'd4;
    else if (req[3]) grant = 3'd3;
    else if (req[2]) grant = 3'd2;
    else if (req[1]) grant = 3'd1;
    else grant = 3'd0;
  end
  assign valid = (req != 8'd0);
endmodule
""", inputs=[("req", 8)], outputs=[("grant", 3), ("valid", 1)])

DESIGNS["barrel8"] = dict(seq=False, src="""
module barrel8(input [7:0] din, input [2:0] sh, input dir, output reg [7:0] dout);
  always @(*) begin
    if (dir) dout = din >> sh;
    else dout = din << sh;
  end
endmodule
""", inputs=[("din", 8), ("sh", 3), ("dir", 1)], outputs=[("dout", 8)])

DESIGNS["cmp8"] = dict(seq=False, src="""
module cmp8(input [7:0] a, input [7:0] b, output lt, output eq, output gt);
  assign lt = (a < b);
  assign eq = (a == b);
  assign gt = (a > b);
endmodule
""", inputs=[("a", 8), ("b", 8)], outputs=[("lt", 1), ("eq", 1), ("gt", 1)])

DESIGNS["mult4"] = dict(seq=False, src="""
module mult4(input [3:0] a, input [3:0] b, output [7:0] p);
  assign p = a * b;
endmodule
""", inputs=[("a", 4), ("b", 4)], outputs=[("p", 8)])

DESIGNS["decode3to8"] = dict(seq=False, src="""
module decode3to8(input [2:0] sel, input en, output reg [7:0] y);
  always @(*) begin
    if (!en) y = 8'd0;
    else begin
      case (sel)
        3'd0: y = 8'b00000001;
        3'd1: y = 8'b00000010;
        3'd2: y = 8'b00000100;
        3'd3: y = 8'b00001000;
        3'd4: y = 8'b00010000;
        3'd5: y = 8'b00100000;
        3'd6: y = 8'b01000000;
        default: y = 8'b10000000;
      endcase
    end
  end
endmodule
""", inputs=[("sel", 3), ("en", 1)], outputs=[("y", 8)])

DESIGNS["counter8"] = dict(seq=True, src="""
module counter8(input clk, input rst, input en, input load, input [7:0] din,
                output reg [7:0] q, output tc);
  always @(posedge clk) begin
    if (rst) q <= 8'd0;
    else if (load) q <= din;
    else if (en) q <= q + 8'd1;
  end
  assign tc = (q == 8'hFF);
endmodule
""", inputs=[("rst", 1), ("en", 1), ("load", 1), ("din", 8)], outputs=[("q", 8), ("tc", 1)])

DESIGNS["shiftreg8"] = dict(seq=True, src="""
module shiftreg8(input clk, input rst, input load, input sin, input [7:0] din,
                 output reg [7:0] q);
  always @(posedge clk) begin
    if (rst) q <= 8'd0;
    else if (load) q <= din;
    else q <= {q[6:0], sin};
  end
endmodule
""", inputs=[("rst", 1), ("load", 1), ("sin", 1), ("din", 8)], outputs=[("q", 8)])

DESIGNS["fsm1011"] = dict(seq=True, src="""
module fsm1011(input clk, input rst, input din, output reg detected, output reg [1:0] state);
  always @(posedge clk) begin
    if (rst) begin
      state <= 2'd0;
      detected <= 1'b0;
    end else begin
      detected <= 1'b0;
      case (state)
        2'd0: if (din) state <= 2'd1; else state <= 2'd0;
        2'd1: if (din) state <= 2'd1; else state <= 2'd2;
        2'd2: if (din) state <= 2'd3; else state <= 2'd0;
        default: if (din) begin
                   state <= 2'd1;
                   detected <= 1'b1;
                 end else state <= 2'd2;
      endcase
    end
  end
endmodule
""", inputs=[("rst", 1), ("din", 1)], outputs=[("detected", 1), ("state", 2)])

DESIGNS["crc8"] = dict(seq=True, src="""
module crc8(input clk, input rst, input en, input din, output reg [7:0] crc);
  wire fb;
  assign fb = crc[7] ^ din;
  always @(posedge clk) begin
    if (rst) crc <= 8'd0;
    else if (en) crc <= {crc[6:0], 1'b0} ^ (fb ? 8'h07 : 8'h00);
  end
endmodule
""", inputs=[("rst", 1), ("en", 1), ("din", 1)], outputs=[("crc", 8)])

DESIGNS["pwm8"] = dict(seq=True, src="""
module pwm8(input clk, input rst, input [7:0] duty, output reg pwm_out, output reg [7:0] cnt);
  always @(posedge clk) begin
    if (rst) begin
      cnt <= 8'd0;
      pwm_out <= 1'b0;
    end else begin
      cnt <= cnt + 8'd1;
      pwm_out <= (cnt < duty);
    end
  end
endmodule
""", inputs=[("rst", 1), ("duty", 8)], outputs=[("pwm_out", 1), ("cnt", 8)])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "cells.v").write_text(CELLS)
    manifest = {}
    for name, d in DESIGNS.items():
        (OUT / f"{name}.v").write_text(d["src"].lstrip())
        manifest[name] = {"top": name, "seq": d["seq"], "clk": "clk" if d["seq"] else None,
                          "inputs": d["inputs"], "outputs": d["outputs"]}
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"{len(manifest)} designs written to {OUT}")
    print("  combinational:", ", ".join(k for k, v in manifest.items() if not v["seq"]))
    print("  sequential:", ", ".join(k for k, v in manifest.items() if v["seq"]))


if __name__ == "__main__":
    main()
