<?php
// Emvoox contact form handler for DreamHost shared hosting (PHP 8).
// Sends the message to $TO with PHP mail(). DreamHost requires the From address to be a mailbox on a domain
// hosted with them, so FROM must be an address @emvoox.com; the visitor's address goes in Reply-To.
// Returns JSON: {"ok": true} or {"ok": false, "error": "..."}.

$TO   = 'dhp@emvoox.com';          // where messages are delivered
$FROM = 'dhp@emvoox.com';          // must be a mailbox on emvoox.com hosted by DreamHost
$MAX_PER_HOUR = 5;                 // per visitor IP

header('Content-Type: application/json; charset=utf-8');
header('X-Content-Type-Options: nosniff');

function reply(int $code, array $body): void {
    http_response_code($code);
    echo json_encode($body, JSON_UNESCAPED_UNICODE);
    exit;
}

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    reply(405, ['ok' => false, 'error' => 'method']);
}

// Only accept posts from our own pages.
$origin = $_SERVER['HTTP_ORIGIN'] ?? '';
if ($origin !== '' && !preg_match('#^https?://(www\.)?emvoox\.com$#', $origin)) {
    reply(403, ['ok' => false, 'error' => 'origin']);
}

// Honeypot: a hidden field people never fill in.
if (trim($_POST['website'] ?? '') !== '') {
    reply(200, ['ok' => true]);
}

function field(string $name, int $max): string {
    $v = trim((string)($_POST[$name] ?? ''));
    $v = str_replace(["\r", "\0"], '', $v);
    return mb_substr($v, 0, $max);
}

$name     = field('name', 120);
$company  = field('company', 160);
$email    = field('email', 160);
$phoneCc  = field('phone_cc', 6);
$phone    = field('phone', 20);
$interest = field('interest', 40);
$message  = field('message', 4000);
$lang     = field('lang', 4);

$interests = ['production', 'brand', 'licensing', 'studio', 'invest', 'other'];
if (!in_array($interest, $interests, true)) $interest = 'other';

// Same rules as the form (assets/js/site.js). Codes map to the inline messages ct.e.<field>.<code>.
$errors = [];
if ($name === '') $errors['name'] = 'req';
elseif (mb_strlen($name) < 2) $errors['name'] = 'min';
if ($email === '') $errors['email'] = 'req';
elseif (!filter_var($email, FILTER_VALIDATE_EMAIL)) $errors['email'] = 'bad';
$phoneDigits = preg_replace('/[\s.\-()]/', '', $phone);
if (!preg_match('/^\+?\d{1,4}$/', $phoneCc)) $errors['phone'] = 'cc';
elseif ($phoneDigits === '') $errors['phone'] = 'req';
elseif (!preg_match('/^\d{6,14}$/', $phoneDigits)) $errors['phone'] = 'bad';
if ($message === '') $errors['message'] = 'req';
elseif (mb_strlen($message) < 10) $errors['message'] = 'min';
// Header fields must stay on one line.
foreach ([$name, $company, $email] as $v) {
    if (strpos($v, "\n") !== false) $errors['name'] = $errors['name'] ?? 'req';
}
if ($errors) {
    reply(422, ['ok' => false, 'error' => 'fields', 'fields' => $errors]);
}
if ($phoneCc[0] !== '+') $phoneCc = '+' . $phoneCc;
$phoneFull = $phoneCc . ' ' . $phone;

// Simple per-IP rate limit in the system temp directory.
$ip = $_SERVER['REMOTE_ADDR'] ?? 'unknown';
$bucket = sys_get_temp_dir() . '/emvoox_contact_' . hash('sha256', $ip);
$now = time();
$hits = [];
if (is_file($bucket)) {
    $hits = array_filter(array_map('intval', explode(',', (string)file_get_contents($bucket))), fn($t) => $t > $now - 3600);
}
if (count($hits) >= $MAX_PER_HOUR) {
    reply(429, ['ok' => false, 'error' => 'rate']);
}
$hits[] = $now;
@file_put_contents($bucket, implode(',', $hits), LOCK_EX);

$subject = 'Emvoox website: ' . $interest . ' (' . $name . ')';
$body = "New message from emvoox.com\n\n"
      . "Name:      $name\n"
      . "Company:   $company\n"
      . "Email:     $email\n"
      . "Phone:     $phoneFull\n"
      . "Interest:  $interest\n"
      . "Language:  $lang\n"
      . "IP:        $ip\n"
      . "Time:      " . gmdate('Y-m-d H:i:s') . " UTC\n\n"
      . "$message\n";

$headers = [
    'From: Emvoox Website <' . $FROM . '>',
    'Reply-To: ' . $email,
    'MIME-Version: 1.0',
    'Content-Type: text/plain; charset=UTF-8',
    'Content-Transfer-Encoding: 8bit',
];

$sent = mail($TO, '=?UTF-8?B?' . base64_encode($subject) . '?=', $body, implode("\r\n", $headers), '-f' . $FROM);
if (!$sent) {
    reply(500, ['ok' => false, 'error' => 'send']);
}
reply(200, ['ok' => true]);
