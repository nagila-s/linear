export class NotFoundError extends Error {
  constructor(message = "ISBN não encontrado") {
    super(message);
    this.name = "NotFoundError";
  }
}
