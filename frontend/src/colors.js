// Layer colours derived from the layer id, so the map and the layer panel agree
// and a layer keeps its colour when a chat is reopened.
const PALETTE = ["#e6194B", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#42d4f4", "#f032e6", "#9A6324"];

export function colorFor(id) {
  let h = 0;
  for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return PALETTE[h % PALETTE.length];
}
