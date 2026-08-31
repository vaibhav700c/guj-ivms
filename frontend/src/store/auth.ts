import { create } from "zustand";

export interface User {
  id: number;
  username: string;
  full_name: string | null;
  role: string;
  department: string | null;
}

interface AuthState {
  token: string | null;
  user: User | null;
  login: (token: string, user: User) => void;
  logout: () => void;
}

export const useAuth = create<AuthState>((set) => ({
  token: localStorage.getItem("ivms_token"),
  user: JSON.parse(localStorage.getItem("ivms_user") || "null"),
  login: (token, user) => {
    localStorage.setItem("ivms_token", token);
    localStorage.setItem("ivms_user", JSON.stringify(user));
    set({ token, user });
  },
  logout: () => {
    localStorage.removeItem("ivms_token");
    localStorage.removeItem("ivms_user");
    set({ token: null, user: null });
  },
}));
