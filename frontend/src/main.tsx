import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import './index.css'
import App from './App.tsx'
import { I18nProvider } from "@/i18n"
import { ThemeProvider } from "@/hooks/use-theme"
import { KanbanPage } from '@/features/kanban/pages/KanbanPage'
import { KanbanTracePage } from '@/features/kanban/pages/KanbanTracePage'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <I18nProvider>
        <ThemeProvider>
          <Routes>
            <Route path="/kanban" element={<KanbanPage />} />
            <Route path="/kanban/:threadId" element={<KanbanTracePage />} />
            <Route path="/*" element={<App />} />
          </Routes>
        </ThemeProvider>
      </I18nProvider>
    </BrowserRouter>
  </StrictMode>,
)
