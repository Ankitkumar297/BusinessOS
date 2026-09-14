import { isAxiosError } from "axios";

export function errorMessage(error: unknown): string {
  if (!isAxiosError(error)) return "Unable to complete the request. Please try again.";
  const detail: unknown = error.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((item: { msg?: string }) => item.msg ?? "Invalid value").join(". ");
  return "Unable to reach BusinessOS. Please try again.";
}
