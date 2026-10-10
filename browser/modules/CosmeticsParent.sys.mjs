/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. https://mozilla.org/MPL/2.0/ */
import { Privacy } from 'resource://cyphra/modules/privacy.sys.mjs';

export class CyphraCosmeticsParent extends JSWindowActorParent {
  receiveMessage(message) {
    if (message.name !== 'Cyphra:GetCosmetics') return null;
    // The caller cannot choose a URL, root context, origin, or Shield mode.
    // Those values come from Gecko's actor metadata in the parent process.
    const url = this.manager.documentURI?.spec || '';
    const top = this.browsingContext.top;
    const topURL = top.currentWindowGlobal?.documentURI?.spec || url;
    // Tokens can select only prevalidated local hiding rules. Privacy bounds
    // and validates classes/IDs and ignores all other message data fields.
    try { return Privacy.getCosmetics(url, topURL, top.id, message.data); }
    catch { return ''; }
  }
}
