'use strict';
(() => {
  const shareButton = document.getElementById('share-order-whatsapp');
  const hint = document.getElementById('os-share-help');
  let readyFile = null;
  let sharing = false;
  if (shareButton && window.isSecureContext && navigator.share && navigator.canShare) {
    const probe = new File([], shareButton.dataset.filename, {type:'application/pdf'});
    if (navigator.canShare({files:[probe]})) {
      // Prepara antes do clique para preservar a ativação exigida no celular.
      fetch(shareButton.dataset.pdfUrl, {credentials:'same-origin',cache:'no-store'})
        .then(response => {
          if (!response.ok || !response.headers.get('content-type')?.includes('application/pdf')) throw new Error('pdf');
          return response.blob();
        })
        .then(blob => {
          const file = new File([blob],shareButton.dataset.filename,{type:'application/pdf'});
          if (navigator.canShare({files:[file]})) {
            readyFile = file;
            if (hint) hint.textContent='PDF pronto. Ao tocar em Enviar no WhatsApp, escolha o WhatsApp e o contato do cliente.';
          }
        })
        .catch(() => {/* A conversa com o link da OS permanece disponível. */});
    }
    shareButton.addEventListener('click', async event => {
      if (!readyFile) return;
      event.preventDefault();
      if (sharing) return;
      sharing = true;
      shareButton.setAttribute('aria-busy','true');
      try {
        await navigator.share({files:[readyFile],title:shareButton.dataset.title,text:shareButton.dataset.message});
      } catch (error) {
        if (error.name !== 'AbortError') {
          readyFile = null;
          if (hint) hint.textContent='Não foi possível compartilhar o arquivo. Toque novamente para abrir a conversa com o link da OS, ou use Salvar PDF.';
        }
      } finally {
        sharing = false;
        shareButton.removeAttribute('aria-busy');
      }
    });
  }
  const qrDialog = document.getElementById('os-qr-dialog');
  document.querySelector('[data-os-qr-open]')?.addEventListener('click', () => qrDialog?.showModal());
  document.querySelector('[data-os-qr-close]')?.addEventListener('click', () => qrDialog?.close());
})();
