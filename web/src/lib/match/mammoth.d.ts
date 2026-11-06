declare module "mammoth/mammoth.browser" {
  export function extractRawText(input: { arrayBuffer: ArrayBuffer }): Promise<{ value: string; messages: unknown[] }>;
  const mammoth: { extractRawText: typeof extractRawText };
  export default mammoth;
}
