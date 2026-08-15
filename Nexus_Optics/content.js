(function() {
    let lastHash = null;
    let lastUrl = null;

    // Fast string hashing function
    function cyrb53(str, seed = 0) {
        let h1 = 0xdeadbeef ^ seed, h2 = 0x41c6ce57 ^ seed;
        for (let i = 0, ch; i < str.length; i++) {
            ch = str.charCodeAt(i);
            h1 = Math.imul(h1 ^ ch, 2654435761);
            h2 = Math.imul(h2 ^ ch, 1597334677);
        }
        h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
        h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
        return 4294967296 * (2097151 & h2) + (h1 >>> 0);
    }

    function countOccurrences(text, words) {
        return words.reduce((acc, word) => {
            let count = 0, pos = text.indexOf(word);
            while (pos !== -1) { count++; pos = text.indexOf(word, pos + word.length); }
            return acc + count;
        }, 0);
    }

    function computeTripwire(text) {
        const t = text.toLowerCase();

        // Tier 1: Instant critical (0.5 each, cap 1.0 fast)
        const adult = countOccurrences(t, [
            'porn', 'xxx', 'hentai', 'nude', 'naked', 'nsfw', 'milf',
            'pornhub', 'xnxx', 'xvideos', 'brazzers', 'redtube', 'xhamster',
            'youporn', 'chaturbate', 'onlyfans', 'rule34', 'nhentai',
            'spankbang', 'eporner', 'blowjob', 'handjob', 'orgasm',
            'boobs', 'tits', 'pussy', 'dick pic', 'sex video',
            'lesbian porn', 'gay porn', 'anal', 'fetish', 'stripper'
        ]);

        // Tier 2: Violence / weapons (0.4 each)
        const violence = countOccurrences(t, [
            'bomb', 'explosive', 'detonator', 'pipebomb', 'pipe bomb',
            'gun', 'firearm', 'weapon', 'kill', 'murder', 'assault rifle',
            'how to make a bomb', 'make a bomb', 'build a bomb',
            'how to make explosives', 'make explosives', 'buy a gun',
            '3d print gun', 'mass shooting', 'school shooting',
            'stab', 'machete', 'molotov', 'grenade', 'ammunition'
        ]);

        // Tier 3: Self-harm (0.5 each)
        const harm = countOccurrences(t, [
            'suicide', 'self-harm', 'cutting myself', 'kill myself',
            'how to commit suicide', 'suicide methods', 'end my life',
            'want to die', 'overdose', 'self injury'
        ]);

        // Tier 4: Drugs (0.3 each)
        const drugs = countOccurrences(t, [
            'cocaine', 'heroin', 'meth', 'methamphetamine', 'marijuana',
            'weed', 'fentanyl', 'ecstasy', 'mdma', 'lsd', 'crack',
            'how to make meth', 'how to cook meth', 'buy drugs online',
            'drug dealer', 'drug market', 'darknet market'
        ]);

        // Tier 5: Gambling (0.2 each)
        const gambling = countOccurrences(t, [
            'casino', 'betting', 'poker', 'slots', 'jackpot',
            '1xbet', 'bet365', 'roulette', 'sportsbet', 'online gambling'
        ]);

        // Tier 6: Bypass / proxy (0.3 each)
        const proxy = countOccurrences(t, [
            'unblock', 'proxy', 'bypass filter', 'bypass school',
            'school proxy', 'school vpn bypass', 'unblocker',
            'unblock school', 'free vpn', 'hide browsing'
        ]);

        // Tier 7: Piracy (0.25 each)
        const piracy = countOccurrences(t, [
            'torrent', 'pirate', 'cracked', 'keygen', 'serial key',
            'tamilrockers', '1337x', 'piratebay', 'rarbg',
            'free download movie', 'watch free online'
        ]);

        // Tier 8: Cheating (0.2 each)
        const cheating = countOccurrences(t, [
            'exam answers', 'cheat sheet', 'homework answers',
            'answer key', 'test answers', 'coursehero',
            'chegg answers', 'brainly answers'
        ]);

        const score = Math.min(adult * 0.5, 1.0) +
                      (violence * 0.4) +
                      (harm * 0.5) +
                      (drugs * 0.3) +
                      (gambling * 0.2) +
                      (proxy * 0.3) +
                      (piracy * 0.25) +
                      (cheating * 0.2);
        return Math.min(Math.max(score, 0.0), 1.0);
    }

    function computeMonetization() {
        const iframes = document.getElementsByTagName('iframe');
        let adIframes = iframes.length > 3 ? iframes.length - 3 : 0;
        const adNetworks = [
            'doubleclick', 'adservice', 'popads', 'googlesyndication',
            'adnxs', 'adsrvr', 'taboola', 'outbrain', 'propellerads',
            'adcash', 'exoclick', 'juicyads', 'trafficjunky',
            'clickadu', 'popcash', 'admaven', 'adsterra'
        ];
        
        for (let i = 0; i < iframes.length; i++) {
            const src = iframes[i].src || '';
            if (adNetworks.some(net => src.includes(net))) adIframes++;
        }

        const popups = Array.from(document.querySelectorAll('div')).filter(div => {
            const style = window.getComputedStyle(div);
            const z = parseInt(style.zIndex, 10) || 0;
            return (style.position === 'fixed' || style.position === 'absolute') && z > 9000;
        }).length;

        const links = document.getElementsByTagName('a');
        let suspDownloads = 0;
        for (let i = 0; i < links.length; i++) {
            const href = (links[i].href || '').toLowerCase();
            if (href.endsWith('.exe') || href.endsWith('.apk') || href.endsWith('.torrent') ||
                href.endsWith('.msi') || href.endsWith('.bat') || href.endsWith('.cmd') ||
                href.includes('download') && (href.includes('.zip') || href.includes('.rar'))) {
                suspDownloads++;
            }
        }

        const score = (adIframes * 0.15) + (popups * 0.2) + (suspDownloads * 0.3);
        return Math.min(Math.max(score, 0.0), 1.0);
    }

    function computeALE() {
        const links = document.getElementsByTagName('a');
        const total = links.length;
        if (total === 0) return 0.0;

        let external = 0, suspicious = 0, redirect = 0;
        const host = window.location.hostname;

        for (let i = 0; i < total; i++) {
            const href = links[i].href || '';
            if (href.startsWith('data:') || href.startsWith('javascript:')) {
                suspicious++;
                continue;
            }

            try {
                const url = new URL(href, window.location.href);
                if (url.hostname && url.hostname !== host) external++;
                if (url.search.length > 200) suspicious++;
                
                const query = url.search.toLowerCase();
                if (query.includes('url=') || query.includes('redirect=') || query.includes('goto=') || query.includes('redir=')) {
                    redirect++;
                }
            } catch(e) {
                // Ignore parse errors, or count as suspicious
            }
        }

        const score = ((external / total) * 0.3) + ((suspicious / total) * 0.4) + ((redirect / total) * 0.3);
        return Math.min(Math.max(score, 0.0), 1.0);
    }

    function captureAndSend() {
        const text = document.body ? document.body.innerText || "" : "";
        const domSnapshot = text.substring(0, 8000);
        const currentHash = cyrb53(domSnapshot);
        const currentUrl = window.location.href;

        // Skip if content and URL are unchanged
        if (currentHash === lastHash && currentUrl === lastUrl) return;

        lastHash = currentHash;
        lastUrl = currentUrl;

        const report = {
            type: "OPTICS_REPORT",
            url: currentUrl,
            url_hostname: window.location.hostname,
            dom_snapshot: domSnapshot,
            title: document.title || "",
            content: domSnapshot,
            tripwire_score: computeTripwire(domSnapshot),
            monetization_score: computeMonetization(),
            ale_score: computeALE()
        };

        try {
            chrome.runtime.sendMessage(report).catch(() => {});
        } catch (err) {}
    }

    // Process on initial load
    if (document.readyState === 'complete') {
        captureAndSend();
    } else {
        window.addEventListener('load', captureAndSend);
    }

    // Periodic interval to monitor DOM mutations efficiently
    setInterval(captureAndSend, 3000);

    // MutationObserver to explicitly catch SPA navigations quicker than setInterval
    let timeout = null;
    const observer = new MutationObserver(() => {
        if (window.location.href !== lastUrl) {
            if (timeout) clearTimeout(timeout);
            timeout = setTimeout(captureAndSend, 500); // Debounce
        }
    });

    if (document.body) {
        observer.observe(document.body, { childList: true, subtree: true });
    } else {
        document.addEventListener('DOMContentLoaded', () => {
            observer.observe(document.body, { childList: true, subtree: true });
        });
    }
})();