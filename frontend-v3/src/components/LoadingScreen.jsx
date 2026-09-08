import { useEffect, useState } from "react";

const MESSAGES = [
  "Warming up the surveillance grid…",
  "Syncing with regional cameras…",
  "Establishing encrypted channels…",
  "Loading operator workspace…",
  "Calibrating detection models…",
  "Almost there, commander…",
];

export default function LoadingScreen({ message }) {
  const [msgIndex, setMsgIndex] = useState(0);
  const [dots, setDots] = useState("");

  useEffect(() => {
    const interval = setInterval(() => {
      setMsgIndex((i) => (i + 1) % MESSAGES.length);
    }, 2800);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const interval = setInterval(() => {
      setDots((d) => (d.length >= 3 ? "" : d + "."));
    }, 400);
    return () => clearInterval(interval);
  }, []);

  const displayMessage = message || MESSAGES[msgIndex];

  return (
    <div className="app-loading">
      <div className="loading-content">
        <div className="loading-pulse" />
        <p className="loading-message">{displayMessage}{dots}</p>
      </div>
    </div>
  );
}
