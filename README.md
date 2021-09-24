## How The Rendering Works For Lists

```JS
import('https://unpkg.com/@lcf.vs/dom-engine/lib/frontend.js')
    .then(({ source: s, render: r }) => {
        const container = {[s]: '<div>{children}</div>'}
        const child = {[s]: '<p>{content} {?optionalContent} {?deep.content}</p>'}

        document.querySelector('#example').append(r({ ...container, children: something.map(e => ({...child, ...e}))}))
    });
// Creates a copy of container, with some copies of child, as children and it merges the properties of `e` & child for each of them
// e.g. something[0] = { content: 123 } -> '<div><p>123 </p></div>'
// e.g. something[0] = { content: 123, optionalContent: 456 } -> '<div><p>123 456</p></div>'
// e.g. something[0] = { content: 123, optionalContent: 456, deep: { content: 789 } } -> '<div><p>123 456 789</p></div>'
```