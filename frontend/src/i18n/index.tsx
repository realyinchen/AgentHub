import { type PropsWithChildren, useCallback, useEffect, useMemo, useState } from "react"
import {
  I18nContext,
  type Locale,
  resolveInitialLocale,
  translate,
  type TranslationParams,
} from "./useI18n"

export type { Locale, TranslationKey, TranslationDictionary, I18nContextValue, TranslationParams } from "./useI18n"

// Named component function for Fast Refresh compatibility
function I18nProvider({ children }: PropsWithChildren) {
  const [locale, setLocale] = useState<Locale>(resolveInitialLocale)

  const t = useCallback(
    (key: string, params?: TranslationParams) =>
      translate(locale, key, params),
    [locale],
  )

  const toggleLocale = useCallback(() => {
    setLocale((previous) => (previous === "zh" ? "en" : "zh"))
  }, [])

  const value = useMemo(
    () => ({
      locale,
      setLocale,
      toggleLocale,
      t,
    }),
    [locale, t, toggleLocale],
  )

  useEffect(() => {
    document.documentElement.lang = locale === "zh" ? "zh-CN" : "en"
    window.localStorage.setItem("agenthub_locale", locale)
  }, [locale])

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export { I18nProvider }

// Re-export useI18n hook separately for Fast Refresh compatibility
export { useI18n } from "./useI18n"
