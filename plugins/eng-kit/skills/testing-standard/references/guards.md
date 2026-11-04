# Guards: keep the gains

A rule that is only written down slips back. Turn the speed rules into checks that fail in CI.

## 1. No per-test seeding of reference data

Laravel / PHPUnit (`tests/Unit/TestStandardGuardTest.php`):

```php
<?php

namespace Tests\Unit;

use PHPUnit\Framework\TestCase;
use RecursiveDirectoryIterator;
use RecursiveIteratorIterator;

class TestStandardGuardTest extends TestCase
{
    /** Files allowed to seed in setUp(), each with a reason. */
    private const ALLOWED = [];

    public function test_no_test_seeds_reference_data_in_set_up(): void
    {
        $offenders = [];
        $dir = dirname(__DIR__);
        foreach (new RecursiveIteratorIterator(new RecursiveDirectoryIterator($dir)) as $file) {
            if (! str_ends_with($file->getFilename(), 'Test.php')) {
                continue;
            }
            $relative = substr($file->getPathname(), strlen($dir) + 1);
            if (self::setUpSeeds(file_get_contents($file->getPathname())) && ! in_array($relative, self::ALLOWED, true)) {
                $offenders[] = $relative;
            }
        }

        $this->assertSame([], $offenders, 'Seed reference data once per database, not in setUp(): see the testing standard.');
    }

    /** True when a setUp() body calls ->seed( (closures inside setUp() included). Uses PHP's tokenizer, so strings and comments cannot fool it. */
    private static function setUpSeeds(string $code): bool
    {
        $tokens = token_get_all($code);
        $count = count($tokens);
        for ($i = 0; $i < $count; $i++) {
            if (! is_array($tokens[$i]) || $tokens[$i][0] !== T_FUNCTION) {
                continue;
            }
            $j = $i + 1;
            while ($j < $count && is_array($tokens[$j]) && $tokens[$j][0] === T_WHITESPACE) {
                $j++;
            }
            if ($j >= $count || ! is_array($tokens[$j]) || strcasecmp($tokens[$j][1], 'setUp') !== 0) {
                continue;
            }
            while ($j < $count && $tokens[$j] !== '{' && $tokens[$j] !== ';') {
                $j++;
            }
            if ($j >= $count || $tokens[$j] === ';') {
                continue;
            }
            $depth = 0;
            $body = '';
            for (; $j < $count; $j++) {
                $opens = $tokens[$j] === '{' || (is_array($tokens[$j]) && in_array($tokens[$j][0], [T_CURLY_OPEN, T_DOLLAR_OPEN_CURLY_BRACES], true));
                if ($opens) {
                    $depth++;
                } elseif ($tokens[$j] === '}' && --$depth === 0) {
                    break;
                }
                $body .= is_array($tokens[$j]) ? $tokens[$j][1] : $tokens[$j];
            }
            if (str_contains($body, '->seed(')) {
                return true;
            }
        }

        return false;
    }
}
```

Same idea elsewhere: a Vitest/Jest test that scans `*.test.*` for `beforeEach(` blocks calling seed/migrate
helpers; a pytest test that scans `conftest.py` for function-scoped fixtures loading data.

## 2. A time budget for tests

- PHPUnit 10+: `ergebnis/phpunit-slow-test-detector` (phpunit.xml extension, reports tests over a limit).
- Vitest: `slowTestThreshold` in the config (reports); Jest: `slowTestThreshold` (reports).
- pytest: `--durations=25` in CI output; `pytest-timeout` for a hard cap on runaway tests.
- Any stack, from the JUnit file in CI (needs Python in the image):

  ```bash
  python3 - junit.xml 5 <<'PY'
  import sys, xml.etree.ElementTree as ET
  path, limit = sys.argv[1], float(sys.argv[2])
  slow = [(c.get("classname") or c.get("class"), c.get("name"), float(c.get("time") or 0))
          for c in ET.parse(path).iter("testcase") if float(c.get("time") or 0) > limit]
  for cls, name, t in sorted(slow, key=lambda x: -x[2])[:30]:
      print(f"{t:6.1f}s  {cls}::{name}")
  print(f"{len(slow)} tests over {limit:g}s")
  PY
  ```

  Start as a report; turn it into a failure (`sys.exit(1)` when new slow tests appear) once the suite is
  inside the budget.

## 3. Order and isolation

- The nightly random-order run (`ci.md`).
- Parallel in CI on every merge request, so isolation problems show up at once.

## 4. The standard where agents read it

Put a short "Testing standard" section in the project's CLAUDE.md (or CONTRIBUTING) that points to these
rules, so every person and agent session follows the same ones.
