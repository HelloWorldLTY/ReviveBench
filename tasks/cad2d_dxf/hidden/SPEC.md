# cadx — specification of the 2D CAD geometry engine (AutoCAD class)

Build `cadx`: a clean-room 2D drafting geometry kernel with a DXF reader/writer and geometric operations.

## Command line (must exist at the workspace root)
    bash run_cad.sh <command.json> <out.json>
`command.json` is one operation; file paths are relative to the working directory.

## DXF subset (AutoCAD 2010 ASCII DXF, group-code/value pairs)
Read and write: HEADER ($ACADVER, $INSUNITS optional), TABLES/LAYER (layer names), ENTITIES: LINE (10/20, 11/21), CIRCLE
(10/20, 40), ARC (10/20, 40, 50 start angle, 51 end angle, counter-clockwise, degrees), LWPOLYLINE (90 count, 70 flags bit 1 =
closed, per-vertex 10/20 and optional 42 bulge = tan(theta/4) of the arc from this vertex to the next; positive = CCW), TEXT (10/20,
40 height, 1 text). Each entity carries 8 = layer and 5 = handle. Files you write must be readable by standard DXF readers
(the grader uses a standard library to read them).

## Operations (all lengths in drawing units; angles in degrees)
- measure: {"op":"measure","dxf":"in.dxf"} -> {"entities":{"LINE":n,...},"layers":[...],"bbox":[xmin,ymin,xmax,ymax],
  "shapes":[{"index":i,"type":"LWPOLYLINE"|"CIRCLE","layer":..,"closed":true,"area":..,"perimeter":..,"centroid":[x,y]}, ...]}
  where shapes lists closed LWPOLYLINEs (bulge arcs included exactly) and CIRCLEs in file order (index = order among those
  shapes). bbox is the exact extent of all entities (arcs/circles by their true extents, TEXT ignored).
- offset: {"op":"offset","dxf":..,"index":i,"distance":d,"out_dxf":..} -> writes one closed LWPOLYLINE (bulge arcs allowed)
  that is the offset of shape i: for d>0 the outward offset with round (arc) corners, i.e. the boundary of the Minkowski sum
  with a disk of radius d; for d<0 the inward offset (boundary of the set of points at distance >= |d| from the outside).
  Output JSON: {"area":..,"perimeter":..}.
- boolean: {"op":"boolean","kind":"union"|"intersection"|"difference","dxf":..,"a":i,"b":j,"out_dxf":..} -> writes the
  result as closed LWPOLYLINEs (one per connected region; holes as additional polylines on layer "HOLES"), JSON
  {"area":..,"regions":n}.
- fillet: {"op":"fillet","dxf":..,"index":i,"radius":r,"out_dxf":..} -> replaces every corner of the (convex) polygon with a
  tangent arc of radius r; JSON {"area":..,"perimeter":..}.
- transform: {"op":"transform","dxf":..,"rotate_deg":a,"scale":s,"translate":[dx,dy],"out_dxf":..} -> applies scale about the
  origin, then rotation about the origin, then translation, to every entity; JSON {"bbox":[...]}.
- write: {"op":"write","entities":[{"type":"LINE","start":[x,y],"end":[x,y],"layer":..}, {"type":"CIRCLE","center":[x,y],"radius":r,..},
  {"type":"ARC","center":..,"radius":..,"start_deg":..,"end_deg":..,..}, {"type":"LWPOLYLINE","points":[[x,y,bulge],...],"closed":true,..},
  {"type":"TEXT","insert":[x,y],"height":h,"text":".."}],"out_dxf":..} -> writes the DXF; JSON {"written":n}.

## Grading
Hidden drawings (polylines with and without arcs, circles, arcs, lines, text, several layers). Tolerances: areas/perimeters/
bbox within 0.1% (offset/fillet/boolean areas within 0.5%), centroids within 1e-3 units, entity counts exact. Files you write are
read back with a standard DXF library and checked geometrically. At least 80% of operations must pass.

## Rules
Python + NumPy only; no ezdxf, shapely, CGAL bindings, OpenCASCADE, etc. (verification checks the environment).
