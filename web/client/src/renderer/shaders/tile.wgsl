struct Uniforms {
  viewport: vec4<f32>,
};

struct VertexIn {
  @location(0) position: vec2<f32>,
  @location(1) uv: vec2<f32>,
  @location(2) origin: vec2<f32>,
  @location(3) size: vec2<f32>,
  @location(4) layer: u32,
};

struct VertexOut {
  @builtin(position) position: vec4<f32>,
  @location(0) uv: vec2<f32>,
  @location(1) @interpolate(flat) layer: u32,
};

@group(0) @binding(0) var<uniform> uniforms: Uniforms;
@group(0) @binding(1) var tileSampler: sampler;
@group(0) @binding(2) var tileTexture: texture_2d_array<f32>;

@vertex
fn vs_main(input: VertexIn) -> VertexOut {
  var out: VertexOut;
  let slide = input.origin + input.position * input.size;
  let ndc_x = ((slide.x - uniforms.viewport.x) / uniforms.viewport.z) * 2.0 - 1.0;
  let ndc_y = 1.0 - ((slide.y - uniforms.viewport.y) / uniforms.viewport.w) * 2.0;
  out.position = vec4<f32>(ndc_x, ndc_y, 0.0, 1.0);
  out.uv = input.uv;
  out.layer = input.layer;
  return out;
}

@fragment
fn fs_main(input: VertexOut) -> @location(0) vec4<f32> {
  let color = textureSample(tileTexture, tileSampler, input.uv, input.layer);
  return color;
}
