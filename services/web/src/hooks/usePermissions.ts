import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/api/client";
import { useAuth } from "@/contexts/AuthContext";

interface Permissions {
  can_run_experiments: boolean;
}

const EMPTY: Permissions = { can_run_experiments: false };

export const usePermissions = () => {
  const { user, loading: authLoading } = useAuth();

  // Server reads the email out of the JWT we send, so we have to be
  // signed in for the call to mean anything. Skip the request entirely
  // when there's no user — saves one round-trip per anonymous page load.
  const { data, isLoading } = useQuery({
    queryKey: ["permissions", user?.id ?? "anon"],
    queryFn: () => apiClient.get<Permissions>("/api/v1/me/permissions"),
    enabled: !!user && !authLoading,
    staleTime: 5 * 60 * 1000,
  });

  return {
    permissions: data ?? EMPTY,
    isLoading: authLoading || (!!user && isLoading),
  };
};
