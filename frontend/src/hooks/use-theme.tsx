import {
  createContext,
  type PropsWithChildren,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react"

type Theme = "light" | "dark"

const STORAGE_KEY = "agenthub_theme"

type ThemeContextValue = {
  theme: Theme
  setTheme: (nextTheme: Theme) => void
  toggleTheme: () => void
}

function resolveInitialTheme(): Theme {
  if (typeof window === "undefined") {
    return "light"
  }

  const stored = window.localStorage.getItem(STORAGE_KEY)
  if (stored === "light" || stored === "dark") {
    return stored
  }

  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"
}

const ThemeContext = createContext<ThemeContextValue>({
  theme: "light",
  setTheme: () => { },
  toggleTheme: () => { },
})

// Create/destroy fade overlay element
function createFadeOverlay(): HTMLDivElement | null {
  if (typeof document === "undefined") return null

  const existing = document.getElementById("theme-fade-overlay")
  if (existing) return existing as HTMLDivElement

  const overlay = document.createElement("div")
  overlay.id = "theme-fade-overlay"
  overlay.style.cssText = `
    position: fixed;
    inset: 0;
    z-index: 9999;
    pointer-events: none;
    opacity: 0;
    transition: opacity 0.5s ease-in-out;
  `
  document.body.appendChild(overlay)
  return overlay
}

function removeFadeOverlay(): void {
  if (typeof document === "undefined") return
  const overlay = document.getElementById("theme-fade-overlay")
  if (overlay) {
    overlay.remove()
  }
}

export function ThemeProvider({ children }: PropsWithChildren) {
  const [theme, setTheme] = useState<Theme>(resolveInitialTheme)
  const [isTransitioning, setIsTransitioning] = useState(false)

  const toggleTheme = useCallback(() => {
    if (isTransitioning) return

    setIsTransitioning(true)
    const overlay = createFadeOverlay()
    const goingToDark = document.documentElement.classList.contains("light") || !document.documentElement.classList.contains("dark")

    // Step 1: Fade in overlay (darkening for dusk, lightening for dawn)
    requestAnimationFrame(() => {
      if (overlay) {
        // When going dark: dark overlay fades in (like night coming)
        // When going light: we switch first, then use light overlay
        overlay.style.backgroundColor = goingToDark
          ? "oklch(0.12 0.02 260)"  // Dark mode bg
          : "oklch(0.98 0.005 250)" // Light mode bg
        overlay.style.opacity = "1"
      }

      // Step 2: After fade in, switch theme and fade out
      setTimeout(() => {
        setTheme((previous) => (previous === "light" ? "dark" : "light"))

        // Step 3: Fade out overlay (revealing the new theme)
        setTimeout(() => {
          if (overlay) {
            overlay.style.opacity = "0"
          }

          // Step 4: Cleanup after fade out completes
          setTimeout(() => {
            removeFadeOverlay()
            setIsTransitioning(false)
          }, 500)
        }, 100)
      }, 400)
    })
  }, [isTransitioning])

  useEffect(() => {
    // Remove no-transitions class after initial hydration to enable smooth transitions
    document.documentElement.classList.remove("no-transitions")
  }, [])

  useEffect(() => {
    const root = document.documentElement
    root.classList.remove("light", "dark")
    root.classList.add(theme)
    window.localStorage.setItem(STORAGE_KEY, theme)
  }, [theme])

  const value = {
    theme,
    setTheme,
    toggleTheme,
  }

  return (
    <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
  )
}

export function useTheme() {
  return useContext(ThemeContext)
}