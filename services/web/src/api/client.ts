import { supabase } from '@/lib/supabase';

const API_BASE_URL = import.meta.env.VITE_CORE_API_URL;
console.log("API_BASE_URL:", API_BASE_URL);

if (!API_BASE_URL) {
  throw new Error("VITE_CORE_API_URL is not defined in environment variables");
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public data?: unknown
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function getAuthHeaders(): Promise<HeadersInit> {
  const headers: HeadersInit = {
    "Content-Type": "application/json",
  };
  
  const { data: { session } } = await supabase.auth.getSession();
  
  if (session?.access_token) {
    headers["Authorization"] = `Bearer ${session.access_token}`;
  }
  
  return headers;
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let errorData: any = {};
    let errorMessage = `HTTP ${response.status}: ${response.statusText}`;
    
    try {
      const text = await response.text();
      if (text) {
        try {
          errorData = JSON.parse(text);
          errorMessage = errorData.detail || errorData.message || errorMessage;
        } catch {
          errorMessage = text;
        }
      }
    } catch (e) {
      console.error("Failed to read error response:", e);
    }
    
    throw new ApiError(response.status, errorMessage, errorData);
  }
  return response.json();
}

export const apiClient = {
  get: async <T>(path: string): Promise<T> => {
    try {
      const headers = await getAuthHeaders();
      const response = await fetch(`${API_BASE_URL}${path}`, {
        method: "GET",
        headers,
      });
      return handleResponse<T>(response);
    } catch (error) {
      if (error instanceof ApiError) throw error;
      const message = error instanceof Error ? error.message : "Network error. Please check your connection.";
      throw new ApiError(0, message);
    }
  },

  post: async <T, D = unknown>(path: string, data?: D): Promise<T> => {
    try {
      const headers = await getAuthHeaders();
      const response = await fetch(`${API_BASE_URL}${path}`, {
        method: "POST",
        headers,
        body: data ? JSON.stringify(data) : undefined,
      });
      return handleResponse<T>(response);
    } catch (error) {
      if (error instanceof ApiError) throw error;
      const message = error instanceof Error ? error.message : "Network error. Please check your connection.";
      throw new ApiError(0, message);
    }
  },

  put: async <T, D = unknown>(path: string, data?: D): Promise<T> => {
    try {
      const headers = await getAuthHeaders();
      const response = await fetch(`${API_BASE_URL}${path}`, {
        method: "PUT",
        headers,
        body: data ? JSON.stringify(data) : undefined,
      });
      return handleResponse<T>(response);
    } catch (error) {
      if (error instanceof ApiError) throw error;
      const message = error instanceof Error ? error.message : "Network error. Please check your connection.";
      throw new ApiError(0, message);
    }
  },

  delete: async <T>(path: string): Promise<T> => {
    try {
      const headers = await getAuthHeaders();
      const response = await fetch(`${API_BASE_URL}${path}`, {
        method: "DELETE",
        headers,
      });
      return handleResponse<T>(response);
    } catch (error) {
      if (error instanceof ApiError) throw error;
      const message = error instanceof Error ? error.message : "Network error. Please check your connection.";
      throw new ApiError(0, message);
    }
  },
};

