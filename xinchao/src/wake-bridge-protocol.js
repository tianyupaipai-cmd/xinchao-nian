// 【连接桥与推送】兼容旧引用：协议常量现在在 bridge-queue.js。
// 代码地图见 src/README.md。
//
// Compatibility export for the core service. The protocol lives in its own
// dependency-free package so notification adapters can consume it separately.
export * from '../packages/wake-bridge/src/index.js';
