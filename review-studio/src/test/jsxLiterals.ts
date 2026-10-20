import ts from "typescript";

/** JSX attributes whose value is read by a person (labels, hints, titles). Everything else (className, data-*, ids) is not text. */
const TEXT_ATTRIBUTES = new Set(["aria-label", "title", "placeholder", "description", "confirmLabel", "label", "what", "eyebrow", "alt"]);
const hasLetters = (text: string) => /\p{L}/u.test(text);

/** String pieces that would be shown if `expression` is rendered: through ternaries, logical operators, `+`, parentheses and templates, never into calls (`t("key")` arguments are keys). */
function shownStrings(expression: ts.Expression, out: string[]): void {
  if (ts.isStringLiteral(expression) || ts.isNoSubstitutionTemplateLiteral(expression)) out.push(expression.text);
  else if (ts.isTemplateExpression(expression)) {
    out.push(expression.head.text);
    for (const span of expression.templateSpans) { shownStrings(span.expression, out); out.push(span.literal.text); }
  } else if (ts.isConditionalExpression(expression)) { shownStrings(expression.whenTrue, out); shownStrings(expression.whenFalse, out); }
  else if (ts.isBinaryExpression(expression)) {
    const operator = expression.operatorToken.kind;
    if (operator === ts.SyntaxKind.AmpersandAmpersandToken) shownStrings(expression.right, out); // the left side is a condition, never shown
    else if (operator === ts.SyntaxKind.BarBarToken || operator === ts.SyntaxKind.QuestionQuestionToken || operator === ts.SyntaxKind.PlusToken) { shownStrings(expression.left, out); shownStrings(expression.right, out); }
    // comparisons (===, !==, <, ...) yield a boolean; their string operands are values being tested, not text
  }
  else if (ts.isParenthesizedExpression(expression) || ts.isAsExpression(expression) || ts.isNonNullExpression(expression)) shownStrings(expression.expression, out);
}

/** Every user-facing literal in a .tsx source that did not go through t(), whitespace-collapsed, in source order. */
export function findJsxLiterals(fileName: string, source: string): string[] {
  const file = ts.createSourceFile(fileName, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const found: string[] = [];
  const add = (text: string) => { const clean = text.replace(/\s+/g, " ").trim(); if (hasLetters(clean)) found.push(clean); };
  const fromExpression = (expression: ts.Expression) => { const pieces: string[] = []; shownStrings(expression, pieces); pieces.forEach(add); };

  const visit = (node: ts.Node): void => {
    if (ts.isJsxText(node)) add(node.text);
    else if (ts.isJsxExpression(node) && node.expression && (ts.isJsxElement(node.parent) || ts.isJsxFragment(node.parent))) fromExpression(node.expression);
    else if (ts.isJsxAttribute(node) && TEXT_ATTRIBUTES.has(node.name.getText(file)) && node.initializer) {
      if (ts.isStringLiteral(node.initializer)) add(node.initializer.text);
      else if (ts.isJsxExpression(node.initializer) && node.initializer.expression) fromExpression(node.initializer.expression);
    }
    ts.forEachChild(node, visit);
  };
  visit(file);
  return found;
}
