import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Base is relative so the built site works from any static host or subfolder.
export default defineConfig({
  plugins: [react()],
  base: './',
})
