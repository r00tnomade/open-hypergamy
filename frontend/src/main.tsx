import "@fontsource-variable/space-grotesk";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import { render } from "preact";
import { App } from "./app";
import "./styles.css";

render(<App />, document.getElementById("root")!);
