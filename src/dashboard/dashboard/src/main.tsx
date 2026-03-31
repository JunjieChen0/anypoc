import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.tsx'
import CostPage from './CostPage.tsx'
import './index.css'

const pathname = window.location.pathname

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {pathname === '/costs' ? <CostPage /> : <App />}
  </StrictMode>,
)
