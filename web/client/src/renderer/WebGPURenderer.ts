import shaderSource from "./shaders/tile.wgsl?raw";

export interface TileInstance {
  x: number;
  y: number;
  width: number;
  height: number;
  layer: number;
}

const QUAD_VERTICES = new Float32Array([
  0, 0, 0, 0,
  1, 0, 1, 0,
  1, 1, 1, 1,
  0, 0, 0, 0,
  1, 1, 1, 1,
  0, 1, 0, 1,
]);

const INSTANCE_STRIDE = 24;

export class WebGPURenderer {
  private canvas: HTMLCanvasElement;
  private context: GPUCanvasContext | null = null;
  private device: GPUDevice | null = null;
  private queue: GPUQueue | null = null;
  private pipeline: GPURenderPipeline | null = null;
  private bindGroup: GPUBindGroup | null = null;
  private uniformBuffer: GPUBuffer | null = null;
  private vertexBuffer: GPUBuffer | null = null;
  private instanceBuffer: GPUBuffer | null = null;
  private instanceCapacity = 0;
  private instanceCount = 0;
  private texture: GPUTexture | null = null;
  private textureView: GPUTextureView | null = null;
  private sampler: GPUSampler | null = null;
  private format: GPUTextureFormat | null = null;
  private tileSize = 0;
  private maxLayers = 0;

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
  }

  async init(): Promise<void> {
    if (!navigator.gpu) {
      throw new Error("WebGPU unavailable");
    }

    const adapter = await navigator.gpu.requestAdapter({ powerPreference: "high-performance" });
    if (!adapter) {
      throw new Error("No suitable GPU adapter found");
    }

    const adapterLimits = adapter.limits;
    this.device = await adapter.requestDevice({
      requiredLimits: {
        maxTextureArrayLayers: Math.min(adapterLimits.maxTextureArrayLayers, 2048),
      },
    });
    this.queue = this.device.queue;
    this.context = this.canvas.getContext("webgpu");
    if (!this.context) {
      throw new Error("Unable to acquire WebGPU context");
    }

    this.format = navigator.gpu.getPreferredCanvasFormat();
    this.configureCanvas();
    this.createPipeline();
    this.createBuffers();
  }

  configureAtlas(tileSize: number, maxLayers = 512): void {
    if (!this.device || !this.format) {
      throw new Error("Renderer not initialized");
    }

    if (this.tileSize === tileSize && this.maxLayers === maxLayers && this.texture) {
      return;
    }

    this.tileSize = tileSize;
    this.maxLayers = maxLayers;

    this.texture?.destroy();
    this.texture = this.device.createTexture({
      size: {
        width: tileSize,
        height: tileSize,
        depthOrArrayLayers: maxLayers,
      },
      format: "rgba8unorm",
      usage: GPUTextureUsage.TEXTURE_BINDING | GPUTextureUsage.COPY_DST | GPUTextureUsage.RENDER_ATTACHMENT,
    });
    this.textureView = this.texture.createView({ dimension: "2d-array" });

    this.sampler = this.device.createSampler({
      magFilter: "linear",
      minFilter: "linear",
    });

    this.createBindGroup();
  }

  setViewport(viewport: { x: number; y: number; width: number; height: number }): void {
    if (!this.device || !this.uniformBuffer) {
      return;
    }
    const data = new Float32Array([viewport.x, viewport.y, viewport.width, viewport.height]);
    this.queue?.writeBuffer(this.uniformBuffer, 0, data);
  }

  setTiles(tiles: TileInstance[]): void {
    if (!this.device) {
      return;
    }
    this.instanceCount = tiles.length;
    this.ensureInstanceBuffer(tiles.length);

    if (!this.instanceBuffer) {
      return;
    }

    const buffer = new ArrayBuffer(this.instanceCount * INSTANCE_STRIDE);
    const view = new DataView(buffer);
    tiles.forEach((tile, idx) => {
      const base = idx * INSTANCE_STRIDE;
      view.setFloat32(base + 0, tile.x, true);
      view.setFloat32(base + 4, tile.y, true);
      view.setFloat32(base + 8, tile.width, true);
      view.setFloat32(base + 12, tile.height, true);
      view.setUint32(base + 16, tile.layer, true);
      view.setUint32(base + 20, 0, true);
    });

    this.queue?.writeBuffer(this.instanceBuffer, 0, buffer);
  }

  async uploadTile(layer: number, bitmap: ImageBitmap): Promise<void> {
    if (!this.device || !this.queue || !this.texture) {
      throw new Error("Renderer not ready for uploads");
    }
    if (layer < 0 || layer >= this.maxLayers) {
      throw new Error(`Layer ${layer} out of bounds`);
    }

    const width = bitmap.width;
    const height = bitmap.height;
    if (width > this.tileSize || height > this.tileSize) {
      throw new Error("Bitmap larger than atlas tile size");
    }

    this.queue.copyExternalImageToTexture(
      { source: bitmap },
      { texture: this.texture, origin: { x: 0, y: 0, z: layer } },
      { width, height }
    );
  }

  render(clearColor: GPUColor = { r: 0.96, g: 0.94, b: 0.91, a: 1 }): void {
    if (!this.device || !this.context || !this.pipeline || !this.bindGroup) {
      return;
    }

    this.configureCanvas();

    const encoder = this.device.createCommandEncoder();
    const renderPass = encoder.beginRenderPass({
      colorAttachments: [
        {
          view: this.context.getCurrentTexture().createView(),
          clearValue: clearColor,
          loadOp: "clear",
          storeOp: "store",
        },
      ],
    });

    renderPass.setPipeline(this.pipeline);
    renderPass.setBindGroup(0, this.bindGroup);
    if (this.vertexBuffer) {
      renderPass.setVertexBuffer(0, this.vertexBuffer);
    }
    if (this.instanceBuffer) {
      renderPass.setVertexBuffer(1, this.instanceBuffer);
    }
    if (this.instanceCount > 0) {
      renderPass.draw(6, this.instanceCount, 0, 0);
    }
    renderPass.end();

    this.device.queue.submit([encoder.finish()]);
  }

  dispose(): void {
    this.texture?.destroy();
    this.uniformBuffer?.destroy();
    this.vertexBuffer?.destroy();
    this.instanceBuffer?.destroy();
  }

  private configureCanvas(): void {
    if (!this.context || !this.device || !this.format) {
      return;
    }
    const pixelRatio = window.devicePixelRatio || 1;
    const width = Math.max(1, Math.floor(this.canvas.clientWidth * pixelRatio));
    const height = Math.max(1, Math.floor(this.canvas.clientHeight * pixelRatio));
    if (this.canvas.width !== width || this.canvas.height !== height) {
      this.canvas.width = width;
      this.canvas.height = height;
    }

    this.context.configure({
      device: this.device,
      format: this.format,
      alphaMode: "opaque",
    });
  }

  private createPipeline(): void {
    if (!this.device || !this.format) {
      return;
    }

    const module = this.device.createShaderModule({ code: shaderSource });

    this.pipeline = this.device.createRenderPipeline({
      layout: "auto",
      vertex: {
        module,
        entryPoint: "vs_main",
        buffers: [
          {
            arrayStride: 16,
            attributes: [
              { shaderLocation: 0, format: "float32x2", offset: 0 },
              { shaderLocation: 1, format: "float32x2", offset: 8 },
            ],
          },
          {
            arrayStride: INSTANCE_STRIDE,
            stepMode: "instance",
            attributes: [
              { shaderLocation: 2, format: "float32x2", offset: 0 },
              { shaderLocation: 3, format: "float32x2", offset: 8 },
              { shaderLocation: 4, format: "uint32", offset: 16 },
            ],
          },
        ],
      },
      fragment: {
        module,
        entryPoint: "fs_main",
        targets: [{ format: this.format }],
      },
      primitive: {
        topology: "triangle-list",
        cullMode: "none",
      },
    });
  }

  private createBuffers(): void {
    if (!this.device) {
      return;
    }

    this.uniformBuffer = this.device.createBuffer({
      size: 16,
      usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
    });

    this.vertexBuffer = this.device.createBuffer({
      size: QUAD_VERTICES.byteLength,
      usage: GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_DST,
      mappedAtCreation: true,
    });
    new Float32Array(this.vertexBuffer.getMappedRange()).set(QUAD_VERTICES);
    this.vertexBuffer.unmap();

    this.ensureInstanceBuffer(0);
  }

  private ensureInstanceBuffer(count: number): void {
    if (!this.device) {
      return;
    }
    if (count <= this.instanceCapacity && this.instanceBuffer) {
      return;
    }
    this.instanceCapacity = Math.max(count, 256);
    this.instanceBuffer?.destroy();
    this.instanceBuffer = this.device.createBuffer({
      size: this.instanceCapacity * INSTANCE_STRIDE,
      usage: GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_DST,
    });
  }

  private createBindGroup(): void {
    if (!this.device || !this.pipeline || !this.uniformBuffer || !this.textureView || !this.sampler) {
      return;
    }

    const layout = this.pipeline.getBindGroupLayout(0);
    this.bindGroup = this.device.createBindGroup({
      layout,
      entries: [
        { binding: 0, resource: { buffer: this.uniformBuffer } },
        { binding: 1, resource: this.sampler },
        { binding: 2, resource: this.textureView },
      ],
    });
  }
}
