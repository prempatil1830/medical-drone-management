import { create } from 'zustand'

const getInitialState = () => {
  try {
    const token = localStorage.getItem('token')
    const userJson = localStorage.getItem('user')
    return {
      token: token || null,
      user: userJson ? JSON.parse(userJson) : null,
      flashMessage: null,
    }
  } catch (error) {
    console.error('Error reading localStorage initial state:', error)
    return { token: null, user: null, flashMessage: null }
  }
}

export const useAuthStore = create((set) => ({
  ...getInitialState(),
  
  setAuth: (token, user) => {
    try {
      localStorage.setItem('token', token)
      localStorage.setItem('user', JSON.stringify(user))
    } catch (e) {
      console.error('Failed to sync auth to localStorage:', e)
    }
    set({ token, user, flashMessage: null })
  },
  
  logout: () => {
    try {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
    } catch (e) {
      console.error('Failed to remove auth from localStorage:', e)
    }
    set({ token: null, user: null, flashMessage: null })
  },

  setFlashMessage: (flashMessage) => set({ flashMessage }),
  clearFlashMessage: () => set({ flashMessage: null }),
}))
