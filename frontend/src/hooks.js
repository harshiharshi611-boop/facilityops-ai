import { useCallback, useEffect, useRef, useState } from "react";
import { errorText } from "./api";

// Calls load() when deps change and returns { data, error, reload }.
// reload() fetches again without blanking the page.
export function useData(load, deps) {
  const [state, setState] = useState({ data: null, error: "" });
  const latest = useRef(0);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback((clear) => {
    const id = ++latest.current;          // ignore answers that arrive too late
    if (clear) setState({ data: null, error: "" });
    return load()
      .then((data) => {
        if (id === latest.current) setState({ data, error: "" });
      })
      .catch((e) => {
        if (id === latest.current) {
          setState({
            data: null,
            error: errorText(e, "Cannot reach the API. Is uvicorn running on port 8000?"),
          });
        }
      });
  }, deps);

  useEffect(() => { run(true); }, [run]);

  return { ...state, reload: () => run(false) };
}