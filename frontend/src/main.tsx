import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { AppProvider } from './state/AppContext'
import { StatusProvider } from './state/StatusContext'
import './styles.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <AppProvider>
        <StatusProvider>
          <App />
        </StatusProvider>
      </AppProvider>
    </BrowserRouter>
  </React.StrictMode>,
)
