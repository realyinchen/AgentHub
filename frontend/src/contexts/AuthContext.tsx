/**
 * Authentication context for AgentHub
 *
 * Provides user authentication state and methods throughout the app
 */

import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react';

// User type
export interface User {
  id: string;
  display_name: string;
  is_mock_user: boolean;
}

// Auth state
interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
}

// Auth context type
interface AuthContextType extends AuthState {
  login: (token: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

// Create context
const AuthContext = createContext<AuthContextType | undefined>(undefined);

// API base URL
const API_BASE = '/api/v1';

interface AuthProviderProps {
  children: ReactNode;
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [state, setState] = useState<AuthState>({
    user: null,
    isAuthenticated: false,
    isLoading: true,
  });

  // Fetch current user from API
  const fetchUser = useCallback(async (): Promise<User | null> => {
    try {
      const response = await fetch(`${API_BASE}/auth/status`, {
        credentials: 'include', // Include cookies
      });

      if (!response.ok) {
        return null;
      }

      const data = await response.json();

      if (data.authenticated && data.user) {
        return data.user;
      }

      return null;
    } catch (error) {
      console.error('[Auth] Failed to fetch user:', error);
      return null;
    }
  }, []);

  // Refresh user state
  const refreshUser = useCallback(async () => {
    const user = await fetchUser();
    setState({
      user,
      isAuthenticated: !!user,
      isLoading: false,
    });
  }, [fetchUser]);

  // Login with token (set cookie and refresh)
  const login = useCallback(async (_token: string) => {
    // Token is already set in cookie by WebSocket handler
    // Just refresh user state
    await refreshUser();
  }, [refreshUser]);

  // Logout
  const logout = useCallback(async () => {
    try {
      await fetch(`${API_BASE}/auth/logout`, {
        method: 'POST',
        credentials: 'include',
      });
    } catch (error) {
      console.error('[Auth] Logout failed:', error);
    }

    // Clear state
    setState({
      user: null,
      isAuthenticated: false,
      isLoading: false,
    });
  }, []);

  // Initial fetch on mount
  useEffect(() => {
    refreshUser();
  }, [refreshUser]);

  const value: AuthContextType = {
    ...state,
    login,
    logout,
    refreshUser,
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

// Hook to use auth context
export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}

// Export context for advanced usage
export { AuthContext };