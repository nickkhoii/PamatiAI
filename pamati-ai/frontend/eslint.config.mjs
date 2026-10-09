import { defineConfig, globalIgnores } from "eslint/config";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import jsxA11y from "eslint-plugin-jsx-a11y";

export default defineConfig([
  ...tseslint.configs.recommended,
  { files: ["src/**/*.{ts,tsx}"], plugins: { "react-hooks": reactHooks, "jsx-a11y": jsxA11y },
    rules: { "react-hooks/rules-of-hooks": "error", "react-hooks/exhaustive-deps": "error",
      "no-eval": "error", "no-implied-eval": "error",
      "no-restricted-syntax": ["error",
        { selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']", message: "Render participant/provider text as escaped React children." },
        { selector: "MemberExpression[property.name='innerHTML']", message: "Do not insert participant/provider text as HTML." }],
      ...jsxA11y.configs.recommended.rules } },
  globalIgnores([".next/**", "next-env.d.ts", "tests/**"])
]);
