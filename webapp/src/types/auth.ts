// Auth wire contracts. Mirror of backend app/schemas.py auth models.

export interface User {
  id: number;
  onlysales_id: string;
  email: string;
  name: string | null;
  scope: string | null;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  user: User;
}

export interface MeResponse {
  user: User;
}
