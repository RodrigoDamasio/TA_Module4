import { useCallback, useEffect, useState } from "react";
import { ApiError } from "@/lib/api";

interface State<T> {
  data: T | null;
  error: ApiError | null;
}

/** Loads data once (and on `reload()`). State is only set from the promise callbacks. */
export function useLoad<T>(load: () => Promise<T>) {
  const [state, setState] = useState<State<T>>({ data: null, error: null });
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let alive = true;
    load().then(
      (data) => alive && setState({ data, error: null }),
      (err: unknown) =>
        alive &&
        setState((s) => ({
          data: s.data,
          error: err instanceof ApiError ? err : new ApiError("server", "Could not load data."),
        })),
    );
    return () => {
      alive = false;
    };
    // `load` is a module-level API function; reloading is driven by `version`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  return { ...state, loading: state.data === null && state.error === null, reload };
}
