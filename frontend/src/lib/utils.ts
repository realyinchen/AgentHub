import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Generate a UUID v4 compatible with both secure (HTTPS) and non-secure (HTTP) contexts.
 * Uses crypto.randomUUID() when available, falls back to a polyfill otherwise.
 */
export function generateUUID(): string {
  // Try native crypto.randomUUID first (requires secure context)
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID()
  }
  
  // Fallback: UUID v4 polyfill
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    const v = c === "x" ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}
