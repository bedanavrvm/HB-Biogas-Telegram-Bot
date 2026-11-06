export type TableCatalogue = {key:string;label:string;numbering:string;columns:{id:string;label:string}[]}[];
export type TableLayout = {order:string[];freeze_through:string};
export type LayoutPreference = {table_layouts?:Record<string,TableLayout>;table_catalogue?:TableCatalogue};
declare const layouts: {
  configure(tables:TableCatalogue|undefined, layouts:Record<string,TableLayout>|undefined):void;
  attach(key:string, api:unknown, element:HTMLElement):{refresh():void;dispose():void};
  mount(element:HTMLElement, handlers:{load:()=>Promise<LayoutPreference>;save:(payload:Record<string,unknown>)=>Promise<LayoutPreference>}):void;
};
export default layouts;
