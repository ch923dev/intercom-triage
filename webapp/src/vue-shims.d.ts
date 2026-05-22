// Tells TS that .vue imports are valid Vue components.
declare module '*.vue' {
  import type { DefineComponent } from 'vue';
  const component: DefineComponent<Record<string, unknown>, Record<string, unknown>, unknown>;
  export default component;
}

// vuedraggable has incomplete types; declare a permissive shim.
declare module 'vuedraggable' {
  import type { DefineComponent } from 'vue';
  const draggable: DefineComponent<Record<string, unknown>, Record<string, unknown>, unknown>;
  export default draggable;
}
