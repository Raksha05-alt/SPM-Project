/** Display event and booking timestamps in Singapore time, using a 24-hour clock. */
export function formatSgt(value: string): string {
  return `${new Date(value).toLocaleString("en-SG", {
    timeZone: "Asia/Singapore",
    hour12: false,
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })} SGT`;
}
