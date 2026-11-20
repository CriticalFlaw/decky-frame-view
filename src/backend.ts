import { callable } from "@decky/api";
import type { CodecChoice } from "./player";

export interface Settings {
  host: string;
  user: string;
  port: number;
  height: number;
  fps: number;
  codec: CodecChoice;
  paired_key: boolean;
  public_key: string;
}

export interface Result {
  ok: boolean;
  message: string;
  device?: boolean;
  ffmpeg?: boolean;
  steamvr?: boolean;
  hostname?: string;
}

export interface StreamInfo {
  base: string;
  token: string;
  height: number;
  fps: number;
  codec: CodecChoice;
}

export const getSettings = callable<[], Settings>("get_settings");
export const setSettings = callable<[changes: Partial<Settings>], { ok: boolean; message?: string; settings: Settings }>(
  "set_settings",
);
export const pair = callable<[password: string], Result>("pair");
export const testConnection = callable<[], Result>("test_connection");
export const forgetHostKey = callable<[], Result>("forget_host_key");
export const streamInfo = callable<[], StreamInfo>("stream_info");
export const stopStream = callable<[], boolean>("stop_stream");
