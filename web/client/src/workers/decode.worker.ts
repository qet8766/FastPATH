const workerSelf = self as unknown as {
  postMessage(message: unknown, transfer?: Transferable[]): void;
};

self.onmessage = async (event: MessageEvent<ArrayBuffer>) => {
  const buffer = event.data;
  try {
    const blob = new Blob([buffer], { type: "image/jpeg" });
    const bitmap = await createImageBitmap(blob);
    workerSelf.postMessage(bitmap, [bitmap]);
  } catch (error) {
    workerSelf.postMessage({ error: String(error) });
  }
};
