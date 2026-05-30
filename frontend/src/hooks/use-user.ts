import { useCallback, useEffect, useMemo, useState } from "react"
import type { UserInfo } from "@/types"
import { setCurrentUserId } from "@/lib/api"

const STORAGE_KEY = "agenthub_user_id"

export const USERS: UserInfo[] = [
  {
    id: "user-male",
    name: "Jack",
    gender: "male",
    avatar: "",
  },
  {
    id: "user-female",
    name: "Rose",
    gender: "female",
    avatar: "",
  },
]

function readStoredUserId(): string | null {
  if (typeof window === "undefined") return null
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
  }, [])

  // Sync api module on mount in case localStorage had a value
  useEffect(() => {
    const stored = readStoredUserId()
    if (stored) {
      setCurrentUserId(stored)
    }
  }, [])

  const currentUser = useMemo<UserInfo | null>(() => {
    if (!userId) return null
    return USERS.find((u) => u.id === userId) ?? null
  }, [userId])

  return { userId, currentUser, setUserId } as const
}