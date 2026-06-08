import { useCallback, useEffect, useState } from "react"
import { getAuthStatus, mockLogin, logout, type AuthStatus, type MockUser } from "@/lib/api"
import { useAuth } from "@/contexts/AuthContext"

export type { MockUser }

export type UserInfo = {
  id: string
  name: string
  gender: "male" | "female" | "unknown"
}

export function useUser() {
  const [authStatus, setAuthStatus] = useState<AuthStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const { refreshUser } = useAuth()

  // Check auth status on mount
  useEffect(() => {
    checkAuth()
  }, [])

  const checkAuth = useCallback(async () => {
    try {
      const status = await getAuthStatus()
      setAuthStatus(status)
    } catch {
      setAuthStatus({ authenticated: false, user: null })
    } finally {
      setLoading(false)
    }
  }, [])

  const login = useCallback(async (userId: string) => {
    await mockLogin(userId)
    await checkAuth()
  }, [checkAuth])

  const signOut = useCallback(async () => {
    await logout()
    setAuthStatus({ authenticated: false, user: null })
    // Refresh AuthContext to sync authentication state
    await refreshUser()
  }, [refreshUser])

  // For backward compatibility with existing code
  const setUserId = useCallback(async (userId: string | null) => {
    if (userId) {
      await login(userId)
    } else {
      await signOut()
    }
  }, [login, signOut])

  const currentUser: UserInfo | null = authStatus?.user ? {
    id: authStatus.user.id,
    name: authStatus.user.display_name,
    gender: "unknown" as const,
  } : null

  return {
    userId: authStatus?.user?.id ?? null,
    currentUser,
    authenticated: authStatus?.authenticated ?? false,
    loading,
    login,
    signOut,
    checkAuth,
    setUserId, // For backward compatibility
  } as const
}