self.onmessage = async (event: MessageEvent<ArrayBuffer>) => {
  const buffer = event.data;
  try {
    const blob = new Blob([buffer], { type: "image/jpeg" });
    const bitmap = await createImageBitmap(blob);
    (self as DedicatedWorkerGlobalScope).postMessage(bitmap, [bitmap]);
  } catch (error) {
    (self as DedicatedWorkerGlobalScope).postMessage({ error: String(error) });
  }
};
