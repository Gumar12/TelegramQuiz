/**
 * Utility to calculate similarity of two strings, mimicking Python's difflib.SequenceMatcher
 */
export function calculateSimilarity(s1: string, s2: string): number {
  const str1 = (s1 || '').toLowerCase().trim();
  const str2 = (s2 || '').toLowerCase().trim();

  if (str1 === str2) return 1.0;
  if (str1.length === 0 || str2.length === 0) return 0.0;

  // Simple Bigram overlap/Sorensen-Dice coefficient for fast, robust word-part similarity check
  const getBigrams = (str: string) => {
    const bigrams = new Set<string>();
    for (let i = 0; i < str.length - 1; i++) {
      bigrams.add(str.substring(i, i + 2));
    }
    return bigrams;
  };

  const b1 = getBigrams(str1);
  const b2 = getBigrams(str2);

  if (b1.size === 0 || b2.size === 0) {
    // Fallback to simple char intersection if strings are too short
    const s1Chars = new Set(str1.split(''));
    const s2Chars = new Set(str2.split(''));
    const intersection = new Set([...s1Chars].filter(x => s2Chars.has(x)));
    return (2.0 * intersection.size) / (s1Chars.size + s2Chars.size);
  }

  const intersection = new Set([...b1].filter(x => b2.has(x)));
  return (2.0 * intersection.size) / (b1.size + b2.size);
}

/**
 * Validates a single question against Telegram specifications and similarity issues.
 * Returns a list of generated warning strings.
 */
export function validateQuestion(
  question: string,
  options: string[],
  correctIndex: number,
  explanation?: string
): string[] {
  const warnings: string[] = [];

  // 1. Text length checks
  if (!question || question.trim().length === 0) {
    warnings.push('Текст вопроса не может быть пустым.');
  } else if (question.length > 300) {
    warnings.push(`Превышен лимит Telegram для вопроса (300 симв): сейчас ${question.length} симв.`);
  }

  // 2. Options check
  if (!options || options.length < 2) {
    warnings.push('Должно быть как минимум 2 варианта ответа.');
  } else if (options.length > 10) {
    warnings.push('Telegram поддерживает максимум 10 вариантов ответа.');
  }

  options.forEach((opt, idx) => {
    if (!opt || opt.trim().length === 0) {
      warnings.push(`Вариант ответа #${idx + 1} пуст.`);
    } else if (opt.length > 100) {
      warnings.push(`Превышен лимит Telegram для варианта #${idx + 1} (100 симв): сейчас ${opt.length} симв.`);
    }
  });

  // 3. Explanation check
  if (explanation && explanation.length > 200) {
    warnings.push(`Превышен лимит Telegram для объяснения (200 симв): сейчас ${explanation.length} симв.`);
  }

  // 4. Correct index boundary
  if (correctIndex < 0 || correctIndex >= options.length) {
    warnings.push('Не выбран или указан некорректный правильный ответ.');
  }

  // 5. Option similarity warning (using 0.75 ratio)
  for (let i = 0; i < options.length; i++) {
    for (let j = i + 1; j < options.length; j++) {
      if (options[i] && options[j]) {
        const sim = calculateSimilarity(options[i], options[j]);
        if (sim > 0.78) {
          warnings.push(
            `Предупреждение: Обнаружены схожие варианты ответов (${Math.round(sim * 100)}%): "${options[i].substring(0, 20)}..." и "${options[j].substring(0, 20)}..."`
          );
        }
      }
    }
  }

  return warnings;
}
