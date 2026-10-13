/** A file's bytes as base64 (the JSON upload routes take base64 text). */
export async function fileToBase64(file: File): Promise<string> {
  const url = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error ?? new Error("Could not read the file"));
    reader.readAsDataURL(file);
  });
  return url.slice(url.indexOf(",") + 1);
}
