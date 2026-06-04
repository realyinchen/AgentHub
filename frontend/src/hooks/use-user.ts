import { useCallback, useEffect, useMemo, useState } from "react"
import type { UserInfo } from "@/types"
import { setCurrentUserId } from "@/lib/api"
import { readUserIdFromUrl, writeToUrl } from "@/features/chat/utils"

const STORAGE_KEY = "agenthub_user_id"

export const USERS: UserInfo[] = [
  {
    id: "00000000-0000-0000-0000-000000000001",
    name: "Jack",
    gender: "male",
  },
  {
    id: "00000000-0000-0000-0000-000000000002",
    name: "Rose",
    gender: "female",
  },
]

function readStoredUserId(): string | null {
  if (typeof window === "undefined") return null
  // First check URL, then localStorage
  const urlUserId = readUserIdFromUrl()
  if (urlUserId) {
    // Sync to localStorage
    window.localStorage.setItem(STORAGE_KEY, urlUserId)
    return urlUserId
  }
  return window.localStorage.getItem(STORAGE_KEY)
}

function writeStoredUserId(userId: string | null): void {
  if (typeof window === "undefined") return
  if (userId) {
    window.localStorage.setItem(STORAGE_KEY, userId)
  } else {
    window.localStorage.removeItem(STORAGE_KEY)
  }
}

export function useUser() {
  const [userId, setUserIdState] = useState<string | null>(readStoredUserId)

  const setUserId = useCallback((id: string | null) => {
    setUserIdState(id)
    writeStoredUserId(id)
    setCurrentUserId(id)
    // Write to URL (without thread_id)
    writeToUrl(id, null)
  }, [])

  // Sync api module on mount in case localStorage had a value
  useEffect(() => {
    const stored = readStoredUserId()
    if (stored) {
      setCurrentUserId(stored)
      // Ensure URL is updated if userId was from localStorage
      const urlUserId = readUserIdFromUrl()
      if (!urlUserId && stored) {
        writeToUrl(stored, null)
      }
    }
  }, [])

  const currentUser = useMemo<UserInfo | null>(() => {
    if (!userId) return null
    return USERS.find((u) => u.id === userId) ?? null
  }, [userId])

  return { userId, currentUser, setUserId } as const
}
