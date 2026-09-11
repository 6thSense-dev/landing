// Decimal seconds relative to the source origin. Never pass absolute ns through Number.
export function secondsFromNs(ns, origin) {
  const value = BigInt(ns) - BigInt(origin);
  const sign = value < 0n ? "-" : "";
  const magnitude = value < 0n ? -value : value;
  const fraction = (magnitude % 1000000000n).toString().padStart(9, "0").replace(/0+$/, "");
  return `${sign}${magnitude / 1000000000n}${fraction ? `.${fraction}` : ""}`;
}
export function nsFromSeconds(text, origin) {
  if (!/^-?(0|[1-9]\d{0,20})(\.\d{1,9})?$/.test(text)) throw new Error("Use decimal seconds with up to nine decimal places.");
  const negative = text.startsWith("-");
  const [whole, fraction = ""] = text.replace(/^-/, "").split(".");
  const value = BigInt(whole) * 1000000000n + BigInt(fraction.padEnd(9, "0"));
  return (BigInt(origin) + (negative ? -value : value)).toString();
}
